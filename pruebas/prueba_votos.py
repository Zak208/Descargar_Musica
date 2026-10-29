"""Votos 👍 / 👎 de las transiciones del DJ (fase 24): crear, doble clic, cambiar, borrar, filtros, resumen, exportar e importar,
caracteres raros, varios hilos, base borrada, migración desde una base anterior y argumentos inválidos.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_votos.py"""
import csv
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from services import library_db, transition_votes as tv
from services.mix_types import TransitionPlan


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def raises(exc, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc:
        return True
    except Exception:
        return False
    return False


def remove_db():
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(str(library_db.DB_FILE) + suffix)
        except OSError:
            pass


A, B, C = r"C:\Musica\Quevedo - Bzrp 52.mp3", r"C:\Musica\Rosalía - Malamente.mp3", r"C:\Musica\Daft Punk - Get Lucky.mp3"
plan = TransitionPlan(a_start_s=187.5, b_start_s=12.25, length_s=16.0, tempo_ratio_b=1.03, bass_swap_s=8.0, kind="blend",
                      reason="mismo tempo, frase de 8 compases")
info_a = {"title": "Bzrp Session 52", "bpm": 128.0, "tone": "8A", "energy": 0.8}
info_b = {"bpm": 124.5, "tone": "9A", "energy": 0.6}
clock = [1_000_000.0]
tv._now = lambda: clock[0]              # reloj controlado: así se prueba la ventana del doble clic sin esperar

# ---------------------------------------------------------------------------------------------------------- crear
check("sin votos: contadores a cero y sin último voto", tv.count() == {"total": 0, "up": 0, "down": 0} and tv.last_vote() is None
      and tv.votes() == [])
v1 = tv.add_vote(plan, A, B, +1, session="s1", a_info=info_a, b_info=info_b, auto_score=0.82)
check("add_vote devuelve un id entero", isinstance(v1, int) and v1 > 0)
row = tv.last_vote()
check("guarda las canciones, el plan y el voto", row["a_path"] == A and row["b_path"] == B and row["vote"] == 1
      and row["a_start_s"] == 187.5 and row["b_start_s"] == 12.25 and row["length_s"] == 16.0
      and row["tempo_ratio_b"] == 1.03 and row["bass_swap_s"] == 8.0 and row["kind"] == "blend"
      and row["reason"] == "mismo tempo, frase de 8 compases")
check("guarda las fichas (título, tempo, tono, energía)", row["a_title"] == "Bzrp Session 52" and row["a_bpm"] == 128.0
      and row["a_tone"] == "8A" and row["a_energy"] == 0.8 and row["b_bpm"] == 124.5 and row["b_tone"] == "9A"
      and row["b_energy"] == 0.6)
check("sin título en la ficha usa el nombre del archivo", row["b_title"] == "Rosalía - Malamente")
check("guarda origen, sesión, nota del puntuador y fecha", row["source"] == "live" and row["session"] == "s1"
      and row["auto_score"] == 0.82 and row["ts"] == clock[0] and row["tags"] == [] and row["note"] == "")
check("acepta un dict en vez de un TransitionPlan", isinstance(
    tv.add_vote({"a_start_s": 10, "b_start_s": 0, "length_s": 0, "kind": "cut"}, A, C, -1, source="recording"), int))
cut = tv.last_vote()
check("el dict rellena lo que falta (ratio 1, graves sin fijar, sin fichas)", cut["tempo_ratio_b"] == 1.0
      and cut["bass_swap_s"] is None and cut["kind"] == "cut" and cut["a_bpm"] is None and cut["a_tone"] is None
      and cut["source"] == "recording")
check("la fila del dict sin 'kind' usa mezcla", tv.add_vote({"a_start_s": 1, "b_start_s": 2, "length_s": 3}, A, B, +1, source="clip")
      and tv.last_vote()["kind"] == "blend" and tv.last_vote()["source"] == "clip")
check("un plan sin cambio de graves fijado se guarda con None", tv.add_vote(
    TransitionPlan(5.0, 6.0, 7.0), B, C, +1) and tv.last_vote()["bass_swap_s"] is None)

# ---------------------------------------------------------------------------------------------------------- doble clic
clock[0] += 10
n0 = tv.count()["total"]
first = tv.add_vote(plan, B, C, +1, session="s2")
clock[0] += 1.0
again = tv.add_vote(plan, B, C, +1, session="s2")
check("doble clic (mismo voto, mismo plan, 1 s): se ignora y devuelve el id existente", again == first
      and tv.count()["total"] == n0 + 1)
check("el voto contrario enseguida es otro voto", tv.add_vote(plan, B, C, -1, session="s2") not in (None, first))
check("otra sesión, aunque sea el mismo plan, cuenta", tv.add_vote(plan, B, C, +1, session="s3") not in (None, first))
other_plan = TransitionPlan(a_start_s=187.5, b_start_s=12.25, length_s=8.0, kind="blend")
check("otro plan para las mismas canciones cuenta", tv.add_vote(other_plan, B, C, +1, session="s2") not in (None, first))
clock[0] += 2.5
late = tv.add_vote(plan, B, C, +1, session="s2")
check("pasados 2 s el mismo voto vuelve a guardarse", late not in (None, first))

# ---------------------------------------------------------------------------------------------------------- cambiar
vid = tv.add_vote(plan, C, A, +1, session="cambios", note="al principio")
check("change_vote cambia el voto y pone etiquetas", tv.change_vote(vid, -1, tags=["graves", "voces", "graves"]))
got = tv.votes(a_path=C, b_path=A)[0]
check("el voto cambió, las etiquetas sin repetir y la nota no se tocó", got["vote"] == -1 and got["tags"] == ["graves", "voces"]
      and got["note"] == "al principio")
check("change_vote con la nota nueva y sin tocar etiquetas", tv.change_vote(vid, -1, note="chocan los bombos")
      and tv.votes(a_path=C, b_path=A)[0]["tags"] == ["graves", "voces"] and tv.votes(a_path=C, b_path=A)[0]["note"] == "chocan los bombos")
check("una lista vacía borra las etiquetas y '' la nota", tv.change_vote(vid, +1, tags=[], note="")
      and tv.votes(a_path=C, b_path=A)[0]["tags"] == [] and tv.votes(a_path=C, b_path=A)[0]["note"] == "")
check("cambiar un voto que no existe da False", tv.change_vote(999999, +1) is False)

# ---------------------------------------------------------------------------------------------------------- borrar
n1 = tv.count()["total"]
check("delete_vote borra el voto", tv.delete_vote(vid) is True and tv.count()["total"] == n1 - 1 and tv.votes(a_path=C, b_path=A) == [])
check("borrar uno que no existe da False", tv.delete_vote(vid) is False)
check("el id de un voto borrado no se reutiliza", tv.add_vote(plan, C, A, +1, session="otra") > vid)

# ---------------------------------------------------------------------------------------------------------- filtros
remove_db()
clock[0] = 2_000_000.0
ids = {}
for i, (a, b, vote, kind) in enumerate([(A, B, +1, "blend"), (A, C, -1, "blend"), (B, C, +1, "cut"), (B, A, -1, "blend"),
                                        (C, A, +1, "blend")]):
    clock[0] += 100
    ids[i] = tv.add_vote(TransitionPlan(10.0 + i, 0.0, 12.0 if kind == "blend" else 0.0, kind=kind), a, b, vote,
                         tags=["desfase"] if vote < 0 else None)
check("base nueva con cinco votos", tv.count() == {"total": 5, "up": 3, "down": 2})
check("votes() va del más reciente al más antiguo", [r["id"] for r in tv.votes()] == [ids[i] for i in (4, 3, 2, 1, 0)])
check("limit", [r["id"] for r in tv.votes(limit=2)] == [ids[4], ids[3]] and tv.votes(limit=0) == [])
check("since", [r["id"] for r in tv.votes(since=2_000_300)] == [ids[4], ids[3], ids[2]])
check("a_path", {r["id"] for r in tv.votes(a_path=A)} == {ids[0], ids[1]})
check("b_path", {r["id"] for r in tv.votes(b_path=C)} == {ids[1], ids[2]})
check("a_path y b_path a la vez", [r["id"] for r in tv.votes(a_path=A, b_path=C)] == [ids[1]])
check("vote", {r["id"] for r in tv.votes(vote=-1)} == {ids[1], ids[3]} and len(tv.votes(vote=+1)) == 3)
check("filtros combinados", [r["id"] for r in tv.votes(a_path=B, vote=-1, since=2_000_000)] == [ids[3]])
check("una ruta sin votos da lista vacía", tv.votes(a_path=r"C:\No\existe.mp3") == [])
check("la ruta se reconoce aunque cambien mayúsculas y barras (Windows)",
      os.name != "nt" or {r["id"] for r in tv.votes(a_path=A.lower().replace("\\", "/"))} == {ids[0], ids[1]})
check("last_vote es el más reciente", tv.last_vote()["id"] == ids[4])

# ---------------------------------------------------------------------------------------------------------- resumen
clock[0] = 2_000_000.0 + 500 + 10 * 86400            # los cinco votos tienen ya 10 días; se añade uno de hoy
today = tv.add_vote(TransitionPlan(1.0, 1.0, 1.0), A, B, +1, tags=["graves", "volumen"], source="clip")
tv.change_vote(ids[1], -1, tags=["desfase", "graves"])
s = tv.summary()
check("resumen: totales", (s["total"], s["up"], s["down"]) == (6, 4, 2) and s["error"] is False)
check("resumen: por tipo de transición", s["by_kind"]["blend"] == {"total": 5, "up": 3, "down": 2}
      and s["by_kind"]["cut"] == {"total": 1, "up": 1, "down": 0})
check("resumen: por etiqueta", s["by_tag"]["graves"] == {"total": 2, "up": 1, "down": 1}
      and s["by_tag"]["desfase"] == {"total": 2, "up": 0, "down": 2} and s["by_tag"]["volumen"] == {"total": 1, "up": 1, "down": 0})
check("resumen: por origen", s["by_source"]["live"]["total"] == 5 and s["by_source"]["clip"]["total"] == 1)
check("resumen: últimos 7 días", s["last_7_days"] == {"total": 1, "up": 1, "down": 0})
check("resumen: canciones y parejas distintas", s["distinct_tracks"] == 3 and s["distinct_pairs"] == 5)
check("resumen: lo que falta para 100, 300 y 1000", [(m["goal"], m["missing"], m["reached"]) for m in s["milestones"]]
      == [(100, 94, False), (300, 294, False), (1000, 994, False)] and all(m["meaning"] for m in s["milestones"]))
for i in range(100):
    clock[0] += 3
    tv.add_vote(TransitionPlan(float(i), 0.0, 10.0), C, B, +1, session="masivo")
s = tv.summary()
check("con más de 100 votos la primera meta aparece como alcanzada",
      s["milestones"][0] == {"goal": 100, "missing": 0, "reached": True, "meaning": s["milestones"][0]["meaning"]}
      and s["milestones"][1]["missing"] == 300 - 106)

# ---------------------------------------------------------------------------------------------------------- caracteres raros
remove_db()
weird_title = 'Canción, "con comillas", tildes áéíóú ñ Ü,\ny salto de línea; ¿qué tal? 日本語 🎵'
weird_note = 'Primera línea, con coma\nSegunda "entre comillas"\r\nTercera;con;puntos y coma\t(tab) y ñandú 🎧'
weird_path = r"C:\Música\Ñandú, 'el' mejor\Canción \"rara\".mp3"
clock[0] += 5
wid = tv.add_vote({"a_start_s": 1.5, "b_start_s": 2.5, "length_s": 3.5}, weird_path, B, -1, session='ses,ión "1"\n',
                  tags=["otro", "corte_brusco"], note=weird_note, a_info={"title": weird_title, "tone": "11B"})
got = tv.last_vote()
check("tildes, comas, comillas, saltos de línea y emojis se guardan tal cual", got["a_title"] == weird_title
      and got["note"] == weird_note and got["a_path"] == weird_path and got["session"] == 'ses,ión "1"\n')
for i in range(5):                                   # más filas, para que el archivo tenga varias
    clock[0] += 5
    tv.add_vote({"a_start_s": float(i), "b_start_s": 0, "length_s": 4}, A, B, +1, note=f"nota {i}, ¡hola!\nlínea 2")
tmpdir = tempfile.mkdtemp(prefix="votos_")
p_json, p_csv = os.path.join(tmpdir, "sub", "votos.json"), os.path.join(tmpdir, "votos.csv")
before = tv.votes()[::-1]
check("export_json crea el archivo (y la carpeta que falte)", tv.export_json(p_json) is True and os.path.isfile(p_json))
with open(p_json, "rb") as fh:
    raw = fh.read()
check("el JSON es utf-8 legible (sin \\u escapes de las tildes) y trae todos los votos",
      "áéíóú".encode("utf-8") in raw and len(json.loads(raw.decode("utf-8"))["votes"]) == 6
      and json.loads(raw.decode("utf-8"))["count"] == 6)
check("export_csv crea el archivo", tv.export_csv(p_csv) is True and os.path.isfile(p_csv))
with open(p_csv, "r", encoding="utf-8", newline="") as fh:
    table = list(csv.DictReader(fh))
check("el CSV tiene una fila por voto y las cabeceras de las columnas", len(table) == 6 and list(table[0]) == list(tv.COLUMNS))
weird_row = next(r for r in table if r["id"] == str(wid))
check("el CSV conserva comas, comillas y saltos de línea dentro de títulos y notas", weird_row["a_title"] == weird_title
      and weird_row["note"].replace("\r\n", "\n") == weird_note.replace("\r\n", "\n") and weird_row["a_path"] == weird_path
      and json.loads(weird_row["tags"]) == ["otro", "corte_brusco"])
check("exportar no deja archivos temporales", not [f for f in os.listdir(tmpdir) if f.endswith(".tmp")]
      and not [f for f in os.listdir(os.path.dirname(p_json)) if f.endswith(".tmp")])
check("exportar a una ruta imposible da False sin lanzar", tv.export_json(os.path.join(tmpdir, "votos.csv", "no.json")) is False
      and tv.export_csv(tmpdir) is False)

# ---------------------------------------------------------------------------------------------------------- importar (ida y vuelta)
check("importar sobre la misma base no duplica nada", tv.import_json(p_json) == 0 and tv.count()["total"] == 6)
remove_db()
check("la base está vacía tras borrarla", tv.count()["total"] == 0)
check("importar en una base vacía recupera todos los votos", tv.import_json(p_json) == 6 and tv.count()["total"] == 6)


def strip_id(rows):
    return [{k: v for k, v in r.items() if k != "id"} for r in rows]


check("la ida y vuelta es exacta (todos los campos menos el id)", strip_id(tv.votes()[::-1]) == strip_id(before))
check("importar otra vez no duplica", tv.import_json(p_json) == 0 and tv.count()["total"] == 6)
tv.change_vote(tv.last_vote()["id"], -1, note="cambiado después de la copia")
check("una copia vieja no duplica un voto que se editó después", tv.import_json(p_json) == 0 and tv.count()["total"] == 6)
clock[0] += 10
tv.add_vote(plan, B, C, +1, session="nuevo")
check("importa solo los votos que faltan", tv.delete_vote(tv.votes(a_path=weird_path)[0]["id"]) and tv.import_json(p_json) == 1
      and tv.count()["total"] == 7)
bad = os.path.join(tmpdir, "malo.json")
with open(bad, "w", encoding="utf-8") as fh:
    fh.write("{esto no es json")
check("un archivo roto o que no existe da None y no añade nada", tv.import_json(bad) is None
      and tv.import_json(os.path.join(tmpdir, "nada.json")) is None and tv.count()["total"] == 7)
mixed = os.path.join(tmpdir, "mezclado.json")
good = {"ts": 5.0, "a_path": "x.mp3", "b_path": "y.mp3", "a_start_s": 1, "b_start_s": 2, "length_s": 3, "vote": 1}
with open(mixed, "w", encoding="utf-8") as fh:
    json.dump([good, {**good, "ts": 6.0, "vote": 7}, {**good, "ts": 7.0, "a_path": ""}, {**good, "ts": None}, "basura", 3,
               {**good, "ts": 8.0, "length_s": "mucho"}, {**good, "ts": 9.0, "tags": ["etiqueta_futura"], "source": "live"},
               {**good, "ts": 10.0, "source": "radio"}], fh)
check("las filas inválidas se saltan y las buenas entran", tv.import_json(mixed) == 2 and tv.count()["total"] == 9)
check("una etiqueta que ya no existe en TAGS se conserva al importar", "etiqueta_futura" in
      tv.votes(a_path="x.mp3", since=9.0)[0]["tags"])

# ---------------------------------------------------------------------------------------------------------- copias
check("backup crea una copia fechada que se puede importar", (lambda p: p and os.path.isfile(p) and
                                                              json.load(open(p, encoding="utf-8"))["count"] == 9)(tv.backup()))
for i in range(4):
    clock[0] += 1
    tv.backup(max_keep=3)
check("backup conserva solo las últimas copias", len(list(tv.BACKUP_DIR.glob("votos_*.json"))) == 3)
remove_db()
check("backup sin votos no crea nada", tv.backup() is None)

# ---------------------------------------------------------------------------------------------------------- rename_path
remove_db()
clock[0] += 100
for a, b in ((A, B), (B, A), (A, C), (C, B)):
    clock[0] += 5
    tv.add_vote(plan, a, b, +1)
new_a = r"D:\Nueva carpeta\Quevedo - Bzrp 52.mp3"
check("rename_path cambia la ruta en las dos columnas (3 apariciones)", tv.rename_path(A, new_a) == 3)
check("los votos siguen con la canción en su ruta nueva", len(tv.votes(a_path=new_a)) == 2 and len(tv.votes(b_path=new_a)) == 1
      and tv.votes(a_path=A) == [] and tv.votes(b_path=A) == [])
check("la otra canción no se tocó", len(tv.votes(a_path=B)) == 1 and len(tv.votes(b_path=B)) == 2)
check("repetir el cambio no hace nada", tv.rename_path(A, new_a) == 0 and tv.rename_path(r"Z:\no.mp3", new_a) == 0)
check("distingue mayúsculas solo si el sistema lo hace (Windows no)",
      os.name != "nt" or tv.rename_path(new_a.upper(), A) == 3)
check("rename_path con rutas vacías es un argumento inválido", raises(ValueError, tv.rename_path, "", A)
      and raises(ValueError, tv.rename_path, A, "") and raises(ValueError, tv.rename_path, None, A))

# ---------------------------------------------------------------------------------------------------------- argumentos inválidos
n = tv.count()["total"]
check("el voto solo puede ser +1 o -1", all(raises(ValueError, tv.add_vote, plan, A, B, v) for v in (0, 2, -2, "1", None, 0.5, True, False)))
check("el voto 1.0 y -1.0 valen", tv.add_vote(plan, B, A, 1.0, session="f1") and tv.add_vote(plan, B, A, -1.0, session="f2"))
check("origen desconocido", raises(ValueError, tv.add_vote, plan, A, B, 1, source="radio"))
check("etiqueta desconocida", raises(ValueError, tv.add_vote, plan, A, B, 1, tags=["mal"]) and raises(ValueError, tv.change_vote, 1, 1, tags=["x"]))
check("etiquetas que no son una lista", raises(ValueError, tv.add_vote, plan, A, B, 1, tags=5))
check("una etiqueta suelta como texto vale", tv.add_vote(plan, A, C, 1, tags="voces", session="t") and tv.last_vote()["tags"] == ["voces"])
check("rutas vacías o que no son texto", raises(ValueError, tv.add_vote, plan, "", B, 1) and raises(ValueError, tv.add_vote, plan, A, "  ", 1)
      and raises(ValueError, tv.add_vote, plan, None, B, 1) and raises(ValueError, tv.add_vote, plan, A, 7, 1))
check("plan que no es plan", raises(ValueError, tv.add_vote, None, A, B, 1) and raises(ValueError, tv.add_vote, "plan", A, B, 1)
      and raises(ValueError, tv.add_vote, 5, A, B, 1))
check("plan sin tiempos o con tiempos que no son números", raises(ValueError, tv.add_vote, {"a_start_s": 1}, A, B, 1)
      and raises(ValueError, tv.add_vote, {"a_start_s": 1, "b_start_s": 1, "length_s": "x"}, A, B, 1)
      and raises(ValueError, tv.add_vote, {"a_start_s": float("nan"), "b_start_s": 1, "length_s": 1}, A, B, 1)
      and raises(ValueError, tv.add_vote, {"a_start_s": float("inf"), "b_start_s": 1, "length_s": 1}, A, B, 1))
check("cambiar con un voto inválido", raises(ValueError, tv.change_vote, 1, 0))
check("filtrar con un voto inválido", raises(ValueError, tv.votes, vote=3))
check("los datos opcionales raros se quedan en None en vez de romper", tv.add_vote(
    plan, A, B, 1, session="raro", auto_score="mucho", a_info={"bpm": "rápido", "energy": float("nan"), "tone": 5}, b_info="nada")
      and tv.last_vote()["auto_score"] is None and tv.last_vote()["a_bpm"] is None and tv.last_vote()["a_energy"] is None
      and tv.last_vote()["a_tone"] is None and tv.last_vote()["b_title"] == "Rosalía - Malamente")
check("ninguno de los intentos inválidos guardó nada", tv.count()["total"] == n + 4)

# ---------------------------------------------------------------------------------------------------------- varios hilos a la vez
remove_db()
errors = []
HILOS, CADA = 8, 25


def worker(k):
    try:
        for i in range(CADA):
            vid = tv.add_vote(TransitionPlan(float(k), float(i), 10.0), A, B, +1 if i % 2 else -1, session=f"hilo{k}")
            if not vid:
                errors.append("sin id")
            tv.count()
            tv.votes(limit=3)
    except Exception as e:
        errors.append(repr(e))


threads = [threading.Thread(target=worker, args=(k,)) for k in range(HILOS)]
for t in threads:
    t.start()
for t in threads:
    t.join(60)
check("8 hilos x 25 votos a la vez: sin errores y no se pierde ninguno", not errors and tv.count()["total"] == HILOS * CADA)
check("y los ids son todos distintos", len({r["id"] for r in tv.votes()}) == HILOS * CADA)
remove_db()
results = []
barrier = threading.Barrier(8)
clock[0] += 100


def clicker():
    barrier.wait()
    results.append(tv.add_vote(plan, A, B, +1, session="mismo"))


threads = [threading.Thread(target=clicker) for _ in range(8)]
for t in threads:
    t.start()
for t in threads:
    t.join(30)
check("8 clics simultáneos sobre el mismo plan dan un solo voto", len(set(results)) == 1 and tv.count()["total"] == 1)
stop = threading.Event()
read_errors = []


def reader():
    while not stop.is_set():
        try:
            tv.summary()
            tv.votes()
        except Exception as e:
            read_errors.append(repr(e))


lector = threading.Thread(target=reader)
lector.start()
escritores = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
for t in escritores:
    t.start()
for t in escritores:
    t.join(60)
stop.set()
lector.join(10)
check("leer y resumir mientras otros hilos escriben no falla", not read_errors and tv.count()["total"] == 1 + 4 * CADA)

# ---------------------------------------------------------------------------------------------------------- base borrada
remove_db()
check("con la base borrada se vuelve a crear sola", tv.add_vote(plan, A, B, +1, session="renace") is not None and tv.count()["total"] == 1)
with library_db.connect() as con:
    check("la tabla y sus índices existen", con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name IN "
                                                        "('transition_votes','idx_votes_ts','idx_votes_pair')").fetchone()[0] == 3)
    check("las demás tablas también", {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
          >= {"tracks", "plays", "loudness", "analysis", "transition_votes"})
    check("el esquema lleva su versión", con.execute("PRAGMA user_version").fetchone()[0] == library_db.SCHEMA_VERSION)
    check("la base guarda con escritura segura (WAL)", con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal")

# ---------------------------------------------------------------------------------------------------------- migración desde una base anterior
remove_db()
library_db._ready = False
old = sqlite3.connect(str(library_db.DB_FILE))
old.executescript("""
CREATE TABLE tracks (path TEXT PRIMARY KEY, mtime REAL NOT NULL, title TEXT, artist TEXT, album TEXT, duration INTEGER DEFAULT 0,
    genre TEXT DEFAULT '', year INTEGER DEFAULT 0, track_no INTEGER DEFAULT 0, tagver INTEGER DEFAULT 0);
CREATE TABLE plays (path TEXT PRIMARY KEY, count INTEGER DEFAULT 0, first_ts REAL DEFAULT 0, last_ts REAL DEFAULT 0);
CREATE TABLE loudness (path TEXT PRIMARY KEY, mtime REAL NOT NULL, lufs REAL NOT NULL);
CREATE TABLE analysis (path TEXT PRIMARY KEY, mtime REAL NOT NULL, version INTEGER NOT NULL, bpm REAL, confidence REAL DEFAULT 0,
    energy REAL DEFAULT 0, intro_ms INTEGER DEFAULT 0, outro_ms INTEGER DEFAULT 0, duration_ms INTEGER DEFAULT 0, tone TEXT,
    tone_conf REAL DEFAULT 0, genre TEXT, artist TEXT, loudness_db REAL, brightness_hz REAL, flux REAL, beat_first_s REAL,
    beat_bpm REAL, beat_downbeat INTEGER, beat_conf REAL);
PRAGMA user_version=1;
""")
old.execute("INSERT INTO tracks(path, mtime, title) VALUES ('a.mp3', 1.0, 'Vieja')")
old.execute("INSERT INTO plays(path, count) VALUES ('a.mp3', 7)")
old.execute("INSERT INTO analysis(path, mtime, version, bpm) VALUES ('a.mp3', 1.0, 3, 120.0)")
old.commit()
old.close()
check("una base anterior (sin la tabla de votos) la recibe y sigue funcionando",
      tv.add_vote(plan, A, B, +1, session="migrada") is not None and tv.count()["total"] == 1)
with library_db.connect() as con:
    check("la migración no pierde lo que había", con.execute("SELECT title FROM tracks").fetchone()[0] == "Vieja"
          and con.execute("SELECT count FROM plays").fetchone()[0] == 7
          and con.execute("SELECT bpm FROM analysis").fetchone()[0] == 120.0)
    check("y sube la versión del esquema", con.execute("PRAGMA user_version").fetchone()[0] == library_db.SCHEMA_VERSION)
    columns = [r[1] for r in con.execute("PRAGMA table_info(transition_votes)")]
check("la tabla tiene exactamente las columnas del plan", columns == list(tv.COLUMNS))
library_db._ready = False
with library_db.connect() as con:
    check("repetir la migración no da error ni toca los votos", con.execute("SELECT COUNT(*) FROM transition_votes").fetchone()[0] == 1)
library_db._ready = False
with library_db.connect() as con:
    library_db._migrate(con)
    library_db._migrate(con)
    check("y _migrate se puede llamar varias veces seguidas", True)

# ---------------------------------------------------------------------------------------------------------- si falla la base
real_connect = library_db.connect


def broken():
    raise sqlite3.OperationalError("disco lleno (simulado)")


library_db.connect = broken
check("si la base falla add_vote devuelve None sin lanzar", tv.add_vote(plan, A, B, +1, session="roto") is None)
check("change_vote y delete_vote devuelven False", tv.change_vote(1, 1) is False and tv.delete_vote(1) is False)
check("las consultas devuelven vacío o ceros", tv.votes() == [] and tv.last_vote() is None
      and tv.count() == {"total": 0, "up": 0, "down": 0})
check("el resumen sale a cero con error=True", tv.summary()["total"] == 0 and tv.summary()["error"] is True
      and [m["missing"] for m in tv.summary()["milestones"]] == [100, 300, 1000])
check("rename, exportar, importar y copia no lanzan", tv.rename_path(A, B) is None and tv.export_json(os.path.join(tmpdir, "x.json")) is False
      and tv.export_csv(os.path.join(tmpdir, "x.csv")) is False and tv.import_json(p_json) is None and tv.backup() is None)
check("no queda un archivo a medias tras un export fallido", not os.path.exists(os.path.join(tmpdir, "x.json")))
library_db.connect = real_connect
check("al volver la base todo sigue funcionando", tv.count()["total"] == 1 and tv.add_vote(plan, A, B, -1, session="vuelve") is not None)

print("FIN")
