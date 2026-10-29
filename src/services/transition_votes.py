"""Votos 👍 / 👎 de las transiciones del modo DJ (fase 24): la materia prima de la IA de las fases 25 a 28.

Cada voto guarda qué dos canciones, en qué punto, con qué tipo de transición y con qué parámetros, más los motivos que
marcó quien votó y la nota del puntuador automático si había. Hacen falta entre 300 y 1.500 votos (ver «Cuántos votos harán
falta» en docs/PLAN_DJ.md), así que lo que importa es que los datos sean fiables y no se pierdan:
  * los votos viven en la tabla `transition_votes` de biblioteca.sqlite (conexiones cortas, seguras desde cualquier hilo);
  * cada escritura es una transacción con `synchronous=FULL` (no se pierde un voto aunque se corte la luz);
  * `export_json` / `export_csv` sacan una copia legible y `import_json` la recupera sin duplicar (`backup()` hace copias
    fechadas en la carpeta de datos);
  * nada de aquí lanza al llamador salvo con argumentos inválidos (voto distinto de +1 / -1, etiqueta desconocida, plan sin
    los tiempos...). Si falla la base se anota en el log y se devuelve None / False / [] / ceros (ver cada función).

Uso típico desde la página DJ:
    vote_id = transition_votes.add_vote(plan, a_path, b_path, +1, source="live", session=sesion,
                                        a_info=ficha_a, b_info=ficha_b)
    transition_votes.change_vote(vote_id, -1, tags=["graves"], note="chocan los bombos")   # si se arrepiente o añade motivos
    transition_votes.delete_vote(vote_id)                                                  # deshacer
"""
import csv
import json
import logging
import math
import os
import time
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass

from config import APP_DATA_DIR
from services import library_db

logger = logging.getLogger(__name__)

SOURCES = ("live", "recording", "clip")             # de dónde viene el voto: directo, mix grabado o fragmento suelto
TAGS = ("desfase", "graves", "voces", "volumen", "corte_brusco", "tono", "duracion", "otro")   # motivos que se pueden marcar
DOUBLE_CLICK_S = 2.0                                # el mismo voto sobre el mismo plan en menos de esto se ignora
# Metas de la tabla «Cuántos votos harán falta» del plan: (votos, qué se consigue)
MILESTONES = ((100, "Solo detecta lo claramente malo"),
              (300, "Modelo usable de tu gusto con tus canciones"),
              (1000, "Bueno: elige parejas y duración de mezcla con criterio"))
BACKUP_DIR = APP_DATA_DIR / "copias_votos"
EXPORT_VERSION = 1

COLUMNS = ("id", "ts", "session", "source", "a_path", "b_path", "a_title", "b_title", "a_start_s", "b_start_s", "length_s",
           "tempo_ratio_b", "bass_swap_s", "kind", "reason", "a_bpm", "b_bpm", "a_tone", "b_tone", "a_energy", "b_energy",
           "auto_score", "vote", "tags", "note")
_INSERT_COLUMNS = COLUMNS[1:]
_INSERT_SQL = (f"INSERT INTO transition_votes({', '.join(_INSERT_COLUMNS)}) "
               f"VALUES ({', '.join(':' + c for c in _INSERT_COLUMNS)})")
_PLAN_SAME = "a_start_s IS :a_start_s AND b_start_s IS :b_start_s AND length_s IS :length_s AND kind IS :kind"


def _now() -> float:
    return time.time()


# ----------------------------------------------------------------------------------------------- validación
def _num(value):
    """Número finito como float, o None si no lo es (None, texto, NaN, infinito, booleano)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _required_num(data: Mapping, key: str) -> float:
    number = _num(data.get(key))
    if number is None:
        raise ValueError(f"el plan necesita «{key}» como número (recibido: {data.get(key)!r})")
    return number


def _check_vote(vote) -> int:
    if isinstance(vote, bool) or not isinstance(vote, (int, float)) or vote not in (1, -1):
        raise ValueError(f"el voto solo puede ser +1 o -1 (recibido: {vote!r})")
    return int(vote)


def _check_source(source) -> str:
    if source not in SOURCES:
        raise ValueError(f"origen desconocido {source!r}; los válidos son {SOURCES}")
    return source


def _check_path(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"«{name}» tiene que ser una ruta (texto no vacío), recibido: {value!r}")
    return value


def _check_tags(tags) -> list:
    """Lista sin repetidos y en el mismo orden; lanza ValueError si alguna etiqueta no está en TAGS."""
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, Iterable):
        raise ValueError(f"las etiquetas tienen que ser una lista de textos (recibido: {tags!r})")
    clean = []
    for tag in tags:
        if tag not in TAGS:
            raise ValueError(f"etiqueta desconocida {tag!r}; las válidas son {TAGS}")
        if tag not in clean:
            clean.append(tag)
    return clean


def _plan_fields(plan) -> dict:
    """Los datos del plan (TransitionPlan o dict) listos para la fila. Lanza ValueError si no se puede leer."""
    if is_dataclass(plan) and not isinstance(plan, type):
        data = asdict(plan)
    elif isinstance(plan, Mapping):
        data = dict(plan)
    else:
        raise ValueError(f"el plan tiene que ser un TransitionPlan o un dict (recibido: {type(plan).__name__})")
    ratio = _num(data.get("tempo_ratio_b"))
    kind = data.get("kind")
    return {"a_start_s": _required_num(data, "a_start_s"), "b_start_s": _required_num(data, "b_start_s"),
            "length_s": _required_num(data, "length_s"), "tempo_ratio_b": 1.0 if ratio is None else ratio,
            "bass_swap_s": _num(data.get("bass_swap_s")), "kind": str(kind) if kind else "blend",
            "reason": str(data.get("reason") or "")}


def _info_fields(info, path: str, prefix: str) -> dict:
    """Ficha de una canción (las claves de `TrackInfo`, todas opcionales) → columnas a_* o b_*."""
    info = info if isinstance(info, Mapping) else {}
    title = info.get("title")
    if not isinstance(title, str) or not title.strip():
        title = os.path.splitext(os.path.basename(path))[0]
    tone = info.get("tone")
    return {f"{prefix}_title": title, f"{prefix}_bpm": _num(info.get("bpm")),
            f"{prefix}_tone": tone if isinstance(tone, str) and tone else None, f"{prefix}_energy": _num(info.get("energy"))}


# ----------------------------------------------------------------------------------------------- base de datos
@contextmanager
def _write():
    """Conexión corta con una transacción de escritura que bloquea a otros escritores (así dos hilos no se pisan) y
    que no se da por hecha hasta estar en disco."""
    with library_db.connect() as con:
        con.execute("PRAGMA synchronous=FULL")
        con.execute("BEGIN IMMEDIATE")
        yield con


def _decode(row) -> dict:
    data = {key: row[key] for key in row.keys()}
    try:
        tags = json.loads(data.get("tags") or "[]")
        data["tags"] = [t for t in tags if isinstance(t, str)] if isinstance(tags, list) else []
    except (TypeError, ValueError):
        data["tags"] = []
    data["note"] = data.get("note") or ""
    return data


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)) if path else ""


def _spellings(con, column: str, path: str) -> list:
    """Las formas en que está escrita en la tabla una misma ruta (mayúsculas, barras...). `column` es a_path o b_path."""
    key = _path_key(path)
    return [r[0] for r in con.execute(f"SELECT DISTINCT {column} FROM transition_votes") if _path_key(r[0]) == key]


def _fail(what: str, error: Exception) -> None:
    logger.warning(f"Votos de transiciones: {what}: {error}")


# ----------------------------------------------------------------------------------------------- altas y cambios
def add_vote(plan, a_path, b_path, vote, source="live", session="", tags=None, note="", a_info=None, b_info=None,
             auto_score=None):
    """Guarda un voto y devuelve su id (None si falla la base). `vote` es +1 (👍) o -1 (👎).

    `plan`: un `TransitionPlan` o un dict con sus campos (a_start_s, b_start_s y length_s son obligatorios).
    `a_info` y `b_info`: fichas `TrackInfo` (usa title, bpm, tone y energy; todo opcional).
    Doble clic: el mismo voto de la misma sesión y origen sobre el mismo plan en menos de 2 s no se vuelve a guardar y
    devuelve el id del que ya existe. (Un voto contrario sí se guarda como voto nuevo: para rectificar, usa `change_vote`.)
    Lanza ValueError solo con argumentos inválidos."""
    vote = _check_vote(vote)
    source = _check_source(source)
    a_path = _check_path(a_path, "a_path")
    b_path = _check_path(b_path, "b_path")
    tags = _check_tags(tags)
    row = _plan_fields(plan)
    row.update(_info_fields(a_info, a_path, "a"))
    row.update(_info_fields(b_info, b_path, "b"))
    row.update(a_path=a_path, b_path=b_path, vote=vote, source=source, session=str(session or ""),
               tags=json.dumps(tags, ensure_ascii=False), note=str(note or ""), auto_score=_num(auto_score))
    try:
        with _write() as con:
            now = _now()
            row["ts"] = now
            twin = con.execute(
                "SELECT id FROM transition_votes WHERE session=:session AND source=:source AND a_path=:a_path AND b_path=:b_path "
                f"AND vote=:vote AND {_PLAN_SAME} AND ts>:since ORDER BY id DESC LIMIT 1",
                {**row, "since": now - DOUBLE_CLICK_S}).fetchone()
            if twin is not None:
                return twin["id"]
            return con.execute(_INSERT_SQL, row).lastrowid
    except Exception as e:
        _fail("no se pudo guardar el voto", e)
        return None


def change_vote(vote_id, vote, tags=None, note=None) -> bool:
    """Cambia un voto ya guardado. `tags` y `note` en None se dejan como estaban (una lista vacía o "" sí los borra).
    Devuelve False si el voto no existe o falla la base. Lanza ValueError solo con argumentos inválidos."""
    vote = _check_vote(vote)
    clean_tags = None if tags is None else _check_tags(tags)
    if note is not None:
        note = str(note)
    try:
        with _write() as con:
            sets, params = ["vote=?"], [vote]
            if clean_tags is not None:
                sets.append("tags=?")
                params.append(json.dumps(clean_tags, ensure_ascii=False))
            if note is not None:
                sets.append("note=?")
                params.append(note)
            return con.execute(f"UPDATE transition_votes SET {', '.join(sets)} WHERE id=?", (*params, vote_id)).rowcount > 0
    except Exception as e:
        _fail(f"no se pudo cambiar el voto {vote_id!r}", e)
        return False


def delete_vote(vote_id) -> bool:
    """Borra un voto (por ejemplo, el de «deshacer»). False si no existe o falla la base."""
    try:
        with _write() as con:
            return con.execute("DELETE FROM transition_votes WHERE id=?", (vote_id,)).rowcount > 0
    except Exception as e:
        _fail(f"no se pudo borrar el voto {vote_id!r}", e)
        return False


def rename_path(old, new):
    """Una canción cambió de sitio: actualiza su ruta en todos los votos (como `PlaylistService.relocate`, sin distinguir
    mayúsculas ni tipo de barra en Windows). Devuelve cuántas rutas cambió (None si falla la base)."""
    old = _check_path(old, "old")
    new = _check_path(new, "new")
    try:
        changed = 0
        with _write() as con:
            for column in ("a_path", "b_path"):
                spellings = [s for s in _spellings(con, column, old) if s != new]
                if spellings:
                    marks = ",".join("?" * len(spellings))
                    changed += con.execute(f"UPDATE transition_votes SET {column}=? WHERE {column} IN ({marks})",
                                           (new, *spellings)).rowcount
        return changed
    except Exception as e:
        _fail("no se pudo actualizar la ruta de una canción", e)
        return None


# ----------------------------------------------------------------------------------------------- consultas
def last_vote():
    """El voto más reciente (dict) o None si no hay ninguno (o falla la base)."""
    found = votes(limit=1)
    return found[0] if found else None


def votes(limit=None, since=None, a_path=None, b_path=None, vote=None) -> list:
    """Votos como lista de dicts (con `tags` ya como lista), del más reciente al más antiguo. Filtros opcionales:
    `limit` (cuántos), `since` (epoch: solo desde ese instante), `a_path` / `b_path` (la canción que sale / la que entra) y
    `vote` (+1 o -1). Lista vacía si no hay o falla la base."""
    if vote is not None:
        vote = _check_vote(vote)
    since = None if since is None else float(since)
    limit = None if limit is None else max(0, int(limit))
    try:
        with library_db.connect() as con:
            where, params = [], []
            if since is not None:
                where.append("ts>=?")
                params.append(since)
            for column, path in (("a_path", a_path), ("b_path", b_path)):
                if path is not None:
                    spellings = _spellings(con, column, path)
                    if not spellings:
                        return []
                    where.append(f"{column} IN ({','.join('?' * len(spellings))})")
                    params.extend(spellings)
            if vote is not None:
                where.append("vote=?")
                params.append(vote)
            sql = "SELECT * FROM transition_votes" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY ts DESC, id DESC"
            if limit is not None:
                sql += " LIMIT ?"
                params.append(limit)
            return [_decode(r) for r in con.execute(sql, params)]
    except Exception as e:
        _fail("no se pudieron leer los votos", e)
        return []


def count() -> dict:
    """{"total": n, "up": n, "down": n}. Ceros si falla la base."""
    result = {"total": 0, "up": 0, "down": 0}
    try:
        with library_db.connect() as con:
            for r in con.execute("SELECT vote, COUNT(*) AS n FROM transition_votes GROUP BY vote"):
                result["up" if r["vote"] > 0 else "down"] += r["n"]
        result["total"] = result["up"] + result["down"]
    except Exception as e:
        _fail("no se pudieron contar los votos", e)
    return result


def _tally(bucket: dict, key, vote: int) -> None:
    entry = bucket.setdefault(key, {"total": 0, "up": 0, "down": 0})
    entry["total"] += 1
    entry["up" if vote > 0 else "down"] += 1


def summary() -> dict:
    """Resumen para enseñar en la página: totales, por tipo de transición, por origen, por etiqueta, últimos 7 días,
    canciones y parejas distintas y cuántos votos faltan para cada meta del plan (100, 300 y 1.000).
    Si falla la base devuelve la misma estructura a cero con `"error": True`."""
    result = {"total": 0, "up": 0, "down": 0, "by_kind": {}, "by_source": {}, "by_tag": {},
              "last_7_days": {"total": 0, "up": 0, "down": 0}, "distinct_tracks": 0, "distinct_pairs": 0, "milestones": [],
              "error": False}
    rows = []
    try:
        with library_db.connect() as con:
            rows = con.execute("SELECT ts, kind, source, vote, tags, a_path, b_path FROM transition_votes").fetchall()
    except Exception as e:
        _fail("no se pudo preparar el resumen", e)
        result["error"] = True
    since = _now() - 7 * 86400
    tracks, pairs = set(), set()
    for r in rows:
        vote = r["vote"]
        result["up" if vote > 0 else "down"] += 1
        _tally(result["by_kind"], r["kind"] or "", vote)
        _tally(result["by_source"], r["source"] or "", vote)
        try:
            tags = json.loads(r["tags"] or "[]")
        except (TypeError, ValueError):
            tags = []
        for tag in tags if isinstance(tags, list) else []:
            _tally(result["by_tag"], tag, vote)
        if r["ts"] >= since:
            result["last_7_days"]["total"] += 1
            result["last_7_days"]["up" if vote > 0 else "down"] += 1
        a, b = _path_key(r["a_path"]), _path_key(r["b_path"])
        tracks.update((a, b))
        pairs.add((a, b))
    result["total"] = result["up"] + result["down"]
    result["distinct_tracks"], result["distinct_pairs"] = len(tracks), len(pairs)
    result["milestones"] = [{"goal": goal, "missing": max(0, goal - result["total"]), "reached": result["total"] >= goal,
                             "meaning": meaning} for goal, meaning in MILESTONES]
    return result


# ----------------------------------------------------------------------------------------------- copias
def _write_atomic(path, write) -> None:
    """Escribe en un archivo temporal de la misma carpeta y lo cambia por el definitivo (nunca queda a medias)."""
    path = os.fspath(path)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            write(fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _all_rows() -> list:
    """Todos los votos del más antiguo al más reciente (lanza si falla la base)."""
    with library_db.connect() as con:
        return [_decode(r) for r in con.execute("SELECT * FROM transition_votes ORDER BY ts, id")]


def export_json(path) -> bool:
    """Guarda todos los votos en un JSON (utf-8) que `import_json` sabe recuperar. False si falla algo."""
    try:
        rows = _all_rows()
        payload = {"format": "transition_votes", "version": EXPORT_VERSION, "exported": _now(), "count": len(rows), "votes": rows}
        _write_atomic(path, lambda fh: json.dump(payload, fh, ensure_ascii=False, indent=1))
        return True
    except Exception as e:
        _fail(f"no se pudo exportar a JSON ({path})", e)
        return False


def export_csv(path) -> bool:
    """Guarda todos los votos en un CSV (utf-8, una fila por voto; las etiquetas van como lista JSON en una celda y las
    comas, comillas y saltos de línea de títulos y notas van entre comillas). False si falla algo."""
    try:
        rows = _all_rows()

        def write(fh):
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(COLUMNS)
            for row in rows:
                writer.writerow(json.dumps(row[c], ensure_ascii=False) if c == "tags" else ("" if row[c] is None else row[c])
                                for c in COLUMNS)
        _write_atomic(path, write)
        return True
    except Exception as e:
        _fail(f"no se pudo exportar a CSV ({path})", e)
        return False


def _import_row(item):
    """Una fila de una copia → valores para insertar, o None si no vale (se salta sin parar la importación)."""
    if not isinstance(item, Mapping):
        return None
    try:
        row = _plan_fields(item)
        vote = _check_vote(item.get("vote"))
        source = _check_source(item.get("source", "live"))
        a_path, b_path = _check_path(item.get("a_path"), "a_path"), _check_path(item.get("b_path"), "b_path")
    except ValueError:
        return None
    ts = _num(item.get("ts"))
    if ts is None:
        return None
    tags = item.get("tags")
    if isinstance(tags, str):                        # el CSV guarda las etiquetas como texto JSON
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = []
    tags = [t for t in tags if isinstance(t, str)] if isinstance(tags, list) else []     # se conservan aunque no estén en TAGS
    row.update(_info_fields({k[2:]: item.get(k) for k in ("a_title", "a_bpm", "a_tone", "a_energy")}, a_path, "a"))
    row.update(_info_fields({k[2:]: item.get(k) for k in ("b_title", "b_bpm", "b_tone", "b_energy")}, b_path, "b"))
    row.update(ts=ts, session=str(item.get("session") or ""), source=source, a_path=a_path, b_path=b_path, vote=vote,
               tags=json.dumps(tags, ensure_ascii=False), note=str(item.get("note") or ""), auto_score=_num(item.get("auto_score")))
    return row


def import_json(path):
    """Recupera votos de un JSON hecho con `export_json` y devuelve cuántos añadió (None si no se pudo leer el archivo o
    falla la base; en ese caso no se añade ninguno). Un voto que ya existe (mismo instante, mismas canciones, mismo plan
    y misma sesión) se ignora aunque en la copia tenga otro voto o nota, y las filas inválidas se saltan."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        items = data.get("votes") if isinstance(data, Mapping) else data
        if not isinstance(items, list):
            raise ValueError("el archivo no tiene una lista de votos")
        added = 0
        with _write() as con:
            for item in items:
                row = _import_row(item)
                if row is None:
                    continue
                twin = con.execute("SELECT 1 FROM transition_votes WHERE ts IS :ts AND session=:session AND a_path=:a_path "
                                   f"AND b_path=:b_path AND {_PLAN_SAME} LIMIT 1", row).fetchone()
                if twin is None:
                    con.execute(_INSERT_SQL, row)
                    added += 1
        return added
    except Exception as e:
        _fail(f"no se pudo importar {path}", e)
        return None


def backup(max_keep: int = 10):
    """Copia fechada de todos los votos en la carpeta `copias_votos` de los datos de la aplicación (se conservan las
    `max_keep` más recientes). Llámala de vez en cuando (al arrancar, cada 50 votos...). Devuelve la ruta de la copia, o
    None si no hay votos o falla algo."""
    try:
        if count()["total"] == 0:
            return None
        target = BACKUP_DIR / time.strftime("votos_%Y%m%d_%H%M%S.json", time.localtime(_now()))
        if not export_json(target):
            return None
        for old in sorted(BACKUP_DIR.glob("votos_*.json"))[:-max(1, int(max_keep))]:
            try:
                old.unlink()
            except OSError:
                pass
        return str(target)
    except Exception as e:
        _fail("no se pudo hacer la copia de los votos", e)
        return None
