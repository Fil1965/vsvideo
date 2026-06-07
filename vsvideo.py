#!/usr/bin/env python3
import os
import re
import argparse
import sys
import json
from datetime import datetime, date
import requests
from dotenv import load_dotenv

# ----------------------------------------------------------------------
# 1. WINDOWS COMPATIBILITY MONKEYPATCH
# ----------------------------------------------------------------------
# vsmetaEncoder uses datetime(1900, 1, 1).timestamp(), which raises an OSError on Windows
# because Windows doesn't support negative/pre-epoch timestamps in the C runtime library.
# We override the imported datetime class inside the vsmetaInfo module at runtime to fix this.
import datetime as dt_module
import vsmetaCodec.vsmetaInfo
import vsmetaCodec.vsmetaBase

class SafeDatetime(dt_module.datetime):
    def timestamp(self) -> float:
        try:
            return super().timestamp()
        except OSError:
            return 0.0

vsmetaCodec.vsmetaInfo.datetime = SafeDatetime
vsmetaCodec.vsmetaBase.datetime = SafeDatetime

# Now we can safely import the encoders and classes
from vsmetaCodec.vsmetaEncoder import VsMetaMovieEncoder
from vsmetaCodec.vsmetaInfo import VsMetaInfo, VsMetaImageInfo
from vsmetaCodec.vsmetaDecoder import VsMetaDecoder

# Load environment variables from .env file
load_dotenv()

# TMDb Configuration
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "22a6b971f551a99c7e9c193ed2525763")
TMDB_LANGUAGE = os.getenv("TMDB_LANGUAGE", "es-ES")

# Supported video extensions
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mpg', '.mov', '.wmv', '.m4v')

# ----------------------------------------------------------------------
# SUFFIX CLEANING & PHYSICAL RENAMING FUNCTIONS
# ----------------------------------------------------------------------
def load_cleaner_rules():
    rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")
    if os.path.exists(rules_path):
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("rules", [])
        except Exception as e:
            print(f"[ERROR] No se pudo leer '{rules_path}': {e}")
    
    # Fallback default rules
    default_rules = [
        "[720p][Español][wWw.EliteTorrent.BiZ]",
        "[BluRay 720p X264 MKV][AC3 5.1 Castellano][www.atomixHQ.ONE]",
        "[wWw.EliteTorrent.BiZ]",
        "[www.atomixHQ.ONE]",
        "[720p]",
        "[1080p]",
        "[Español]",
        "[Castellano]"
    ]
    try:
        with open(rules_path, "w", encoding="utf-8") as f:
            json.dump({
                "rules": default_rules,
                "ignored_folders": ["extras", "samples", "trailers", "subtitles"]
            }, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] No se pudo crear '{rules_path}': {e}")
    return default_rules

def load_ignored_folders():
    rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")
    default_ignored = ["extras", "samples", "trailers", "subtitles"]
    if os.path.exists(rules_path):
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("ignored_folders", default_ignored)
        except Exception as e:
            print(f"[ERROR] No se pudo leer '{rules_path}': {e}")
    return default_ignored

def save_cleaner_rules(rules):
    rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.json")
    try:
        data = {}
        if os.path.exists(rules_path):
            with open(rules_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["rules"] = rules
        with open(rules_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] No se pudo guardar '{rules_path}': {e}")

def clean_filename_with_rules(filename, rules):
    base, ext = os.path.splitext(filename)
    new_base = base
    for rule in rules:
        if not rule.strip():
            continue
        # Replace rule case-insensitively
        pattern = re.compile(re.escape(rule), re.IGNORECASE)
        new_base = pattern.sub("", new_base)
    
    # Clean up multiple spaces, dots, dashes, and underscores
    new_base = re.sub(r'\s+', ' ', new_base)
    new_base = new_base.strip(" ._-")
    return new_base + ext

def rename_physical_files(old_filepath, new_basename, verbose=False):
    old_dir = os.path.dirname(old_filepath)
    old_basename = os.path.basename(old_filepath)
    _, ext = os.path.splitext(old_basename)
    
    # Target video filepath
    new_filepath = os.path.join(old_dir, new_basename)
    
    # Handle name collisions
    if os.path.exists(new_filepath) and new_filepath.lower() != old_filepath.lower():
        print(f"  [AVISO] No se renombró el archivo físico para evitar colisión con uno existente:")
        print(f"    Existente: '{new_basename}'")
        print(f"    Conservado original: '{old_basename}'")
        return old_filepath
            
    if new_filepath.lower() != old_filepath.lower():
        print(f"  [RENOMBRADO] Renombrando archivo físico:")
        print(f"    Origen: '{old_basename}'")
        print(f"    Destino: '{new_basename}'")
        try:
            os.rename(old_filepath, new_filepath)
            
            # Also rename any existing .vsmeta
            old_vsmeta = old_filepath + ".vsmeta"
            new_vsmeta = new_filepath + ".vsmeta"
            if os.path.exists(old_vsmeta):
                if os.path.exists(new_vsmeta):
                    os.remove(new_vsmeta)
                os.rename(old_vsmeta, new_vsmeta)
                if verbose:
                    print(f"    [INFO] Renombrado .vsmeta compañero.")
            return new_filepath
        except Exception as e:
            print(f"  [ERROR] No se pudo renombrar el archivo físico: {e}")
    return old_filepath

def detect_removed_suffix(original, refined):
    if not original or not refined:
        return None
    orig_norm = " ".join(original.lower().split())
    ref_norm = " ".join(refined.lower().split())
    
    if ref_norm in orig_norm:
        # Find where refined is in original case-insensitively
        match = re.search(re.escape(refined), original, re.IGNORECASE)
        if match:
            span = match.span()
            removed_parts = []
            prefix = original[:span[0]].strip(" ._-")
            suffix = original[span[1]:].strip(" ._-")
            if prefix:
                removed_parts.append(prefix)
            if suffix:
                removed_parts.append(suffix)
            if removed_parts:
                return " ".join(removed_parts)
    return None

def learn_suffix_if_needed(original_query, new_query):
    if not original_query or not new_query:
        return
    removed = detect_removed_suffix(original_query, new_query)
    if removed:
        # Clean up year/parenthesis/brackets from the learned suffix so we don't accidentally learn year
        removed_clean = re.sub(r'\(\s*(19\d{2}|20\d{2})\s*\)', '', removed)
        removed_clean = re.sub(r'\[\s*(19\d{2}|20\d{2})\s*\]', '', removed_clean)
        removed_clean = re.sub(r'\b(19\d{2}|20\d{2})\b', '', removed_clean)
        
        # Clean up brackets left empty
        removed_clean = re.sub(r'\[\s*\]', '', removed_clean)
        removed_clean = re.sub(r'\(\s*\)', '', removed_clean)
        
        # Normalize spaces
        removed_clean = ' '.join(removed_clean.split()).strip(" ._-")
        
        if len(removed_clean) >= 3:
            print(f"\n[APRENDIZAJE] Se detectó la coletilla eliminada: '{removed_clean}'")
            save_choice = input(f"¿Quieres guardar esta coletilla en 'rules.json' para limpieza automática? (s/n) [Defecto: s]: ").strip().lower()
            if save_choice != 'n':
                rules = load_cleaner_rules()
                if removed_clean not in rules:
                    rules.append(removed_clean)
                    save_cleaner_rules(rules)
                    print(f"  [OK] Coletilla '{removed_clean}' agregada a rules.json.")
                else:
                    print(f"  [INFO] La coletilla '{removed_clean}' ya estaba en rules.json.")

# ----------------------------------------------------------------------
# 2. FILENAME PARSER & CLEANER
# ----------------------------------------------------------------------
def parse_movie_filename(filepath):
    """
    Parses a movie filepath to extract a cleaned movie title and release year.
    It cleans up standard release attributes (e.g. BluRay, Rip, AC3, formats)
    and strips brackets content.
    """
    basename = os.path.basename(filepath)
    base_no_ext, _ = os.path.splitext(basename)

    # Split camelCase (e.g. IronMan -> Iron Man, SpiderMan -> Spider Man)
    base_no_ext = re.sub(r'([a-z])([A-Z])', r'\1 \2', base_no_ext)

    # 1. Try to find a 4-digit year (from 1900 to 2030), supporting delimiters like underscores
    year_match = re.search(r'(?:^|[\s._\-])(19\d{2}|20[0-2]\d|2030)(?:$|[\s._\-])', base_no_ext)
    year = year_match.group(1) if year_match else None

    # If year is found, extract title before the year
    if year_match:
        title_part = base_no_ext[:year_match.start()]
        # Fallback to whole base if prefix is too short/empty
        if len(title_part.strip(" ._-")) > 2:
            base_no_ext = title_part

    # 2. Remove square brackets [...] and parentheses (...)
    base_no_ext = re.sub(r'\[[^\]]*\]', '', base_no_ext)
    base_no_ext = re.sub(r'\([^\)]*\)', '', base_no_ext)

    # 3. Clean up common release quality / codec tags case-insensitively
    junk_words = r'\b(4k(?:remux)?(?:\d+)?|2160p?|1080p?|720p?|remux|bluray|bdr|bdrip|brrip|dvdrip|hdrip|dvd|screener|scr|x264|h264|x265|hevc|xvid|ac3|aac|dts|5\.1|castellano|espanol|spanish|english|latino)\b'
    base_no_ext = re.sub(junk_words, ' ', base_no_ext, flags=re.IGNORECASE)

    # 4. Replace dots, underscores, dashes, and brackets with spaces
    base_no_ext = re.sub(r'[._\-]', ' ', base_no_ext)

    # 5. Remove extra whitespaces
    clean_title = ' '.join(base_no_ext.split()).strip()

    return clean_title, year


def extract_tmdb_id(url_or_id):
    """
    Extracts the TMDB movie ID from a TMDB URL or a raw ID string.
    Supports formats like:
      - 8077
      - https://www.themoviedb.org/movie/8077-alien
      - /movie/8077
    """
    if not url_or_id:
        return None
    url_or_id = str(url_or_id).strip()
    if url_or_id.isdigit():
        return int(url_or_id)
    match = re.search(r'/movie/(\d+)', url_or_id)
    if match:
        return int(match.group(1))
    return None


# ----------------------------------------------------------------------
# 3. TMDB API CLIENT
# ----------------------------------------------------------------------
class TMDbClient:
    def __init__(self, api_key, language="es-ES"):
        self.api_key = api_key
        self.language = language
        self.base_url = "https://api.themoviedb.org/3"

    def search_movie(self, query, year=None):
        """Searches for a movie on TMDb and returns the first result."""
        url = f"{self.base_url}/search/movie"
        params = {
            "api_key": self.api_key,
            "query": query,
            "language": self.language
        }
        if year:
            params["year"] = year

        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            results = response.json().get("results", [])
            return results[0] if results else None
        except Exception as e:
            print(f"[ERROR] Error al buscar película '{query}' en TMDb: {e}")
            return None

    def get_movie_details(self, movie_id):
        """Fetches movie details including credits and release dates."""
        url = f"{self.base_url}/movie/{movie_id}"
        params = {
            "api_key": self.api_key,
            "append_to_response": "credits,release_dates",
            "language": self.language
        }
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[ERROR] Error al obtener detalles de la película (ID {movie_id}) de TMDb: {e}")
            return None

    def download_image(self, path, size="w500"):
        """Downloads an image from TMDb and returns the byte data."""
        if not path:
            return None
        # size can be 'w500' or 'original'
        url = f"https://image.tmdb.org/t/p/{size}{path}"
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            return response.content
        except Exception as e:
            print(f"[ERROR] Error al descargar imagen de TMDb desde {url}: {e}")
            return None


# ----------------------------------------------------------------------
# 4. METADATA MAPPING & VSMETA ENCODING
# ----------------------------------------------------------------------
def extract_certification(release_dates_data, target_country='ES'):
    """Extracts classification rating (certification) from release dates data."""
    results = release_dates_data.get('results', [])
    # 1. Search for target country (default ES)
    for country in results:
        if country.get('iso_3166_1') == target_country:
            for rd in country.get('release_dates', []):
                cert = rd.get('certification')
                if cert:
                    return cert
    # 2. Search for US country
    for country in results:
        if country.get('iso_3166_1') == 'US':
            for rd in country.get('release_dates', []):
                cert = rd.get('certification')
                if cert:
                    return cert
    # 3. Fallback to any non-empty certification found
    for country in results:
        for rd in country.get('release_dates', []):
            cert = rd.get('certification')
            if cert:
                return cert
    return ""


def readline_input(prompt, prefill=""):
    """
    Reads input from console, pre-filling it with a default string
    which the user can edit or delete. Supports Windows and Unix.
    """
    try:
        import readline
        readline.set_startup_hook(lambda: readline.insert_text(prefill))
        try:
            return input(prompt)
        finally:
            readline.set_startup_hook()
    except Exception:
        # Fallback if readline is not available or fails
        if prefill:
            val = input(f"{prompt} (Pulsa Enter para usar '{prefill}'): ").strip()
            return val if val else prefill
        return input(prompt).strip()


def query_movie_with_user(clean_title, year, client, verbose=False):
    """
    Interactively searches for a movie on TMDb.
    Allows the user to select from multiple results or type a new search term.
    """
    search_query = clean_title
    search_year = year

    while True:
        url = f"{client.base_url}/search/movie"
        params = {
            "api_key": client.api_key,
            "query": search_query,
            "language": client.language
        }
        if search_year:
            params["year"] = search_year

        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            results = response.json().get("results", [])
        except Exception as e:
            print(f"[ERROR] Error al buscar en TMDb: {e}")
            results = []

        # Automatic fallback without year if search returned nothing
        if not results and search_year:
            try:
                params.pop("year", None)
                response = requests.get(url, params=params, timeout=15)
                response.raise_for_status()
                results = response.json().get("results", [])
            except Exception:
                pass

        if results:
            print(f"\n[BÚSQUEDA] Resultados de TMDb para '{search_query}'" + (f" ({search_year})" if search_year else "") + ":")
            limit = min(len(results), 5)
            for idx in range(limit):
                res = results[idx]
                title = res.get("title", "Sin título")
                orig_title = res.get("original_title", "")
                res_year = res.get("release_date", "0000-00-00")[:4]
                display = f"  {idx + 1}. {title} ({res_year})"
                if orig_title and orig_title != title:
                    display += f" [Orig: {orig_title}]"
                print(display)

            print(f"  {limit + 1}. Buscar con otro título / refinar nombre...")
            print(f"  {limit + 2}. Introducir URL o ID de TMDb...")
            print(f"  {limit + 3}. Omitir esta película")

            try:
                choice = input(f"Selecciona una opción (1-{limit + 3}) [Defecto: 1]: ").strip()
                if not choice:
                    return results[0]
                choice_idx = int(choice)
                if 1 <= choice_idx <= limit:
                    return results[choice_idx - 1]
                elif choice_idx == limit + 1:
                    new_query = readline_input("Introduce el nuevo título de búsqueda: ", search_query).strip()
                    if new_query:
                        learn_suffix_if_needed(search_query, new_query)
                        search_query = new_query
                        search_year = None  # Reset year for new search term
                    continue
                elif choice_idx == limit + 2:
                    user_input = input("Introduce la URL o ID de TMDb: ").strip()
                    tmdb_id = extract_tmdb_id(user_input)
                    if tmdb_id:
                        details = client.get_movie_details(tmdb_id)
                        if details:
                            return {"id": tmdb_id, "title": details.get("title", "ID " + str(tmdb_id))}
                        else:
                            print(f"[ERROR] No se pudieron obtener detalles para el ID {tmdb_id}.")
                    else:
                        print("[ERROR] Formato de URL o ID no válido.")
                    continue
                else:
                    return None
            except (ValueError, IndexError):
                print("Opción no válida. Omitiendo película.")
                return None
        else:
            print(f"\n[AVISO] No se encontraron resultados para '{search_query}'.")
            print("  1. Buscar con otro título / refinar nombre...")
            print("  2. Introducir URL o ID de TMDb...")
            print("  3. Omitir esta película")
            try:
                choice = input("Selecciona una opción (1-3) [Defecto: 1]: ").strip()
                if not choice:
                    choice_idx = 1
                else:
                    choice_idx = int(choice)
                if choice_idx == 1:
                    choice_refine = readline_input("Introduce el nuevo título de búsqueda: ", search_query).strip()
                    if choice_refine:
                        learn_suffix_if_needed(search_query, choice_refine)
                        search_query = choice_refine
                        search_year = None
                    continue
                elif choice_idx == 2:
                    user_input = input("Introduce la URL o ID de TMDb: ").strip()
                    tmdb_id = extract_tmdb_id(user_input)
                    if tmdb_id:
                        details = client.get_movie_details(tmdb_id)
                        if details:
                            return {"id": tmdb_id, "title": details.get("title", "ID " + str(tmdb_id))}
                        else:
                            print(f"[ERROR] No se pudieron obtener detalles para el ID {tmdb_id}.")
                    else:
                        print("[ERROR] Formato de URL o ID no válido.")
                    continue
                else:
                    return None
            except (ValueError, IndexError):
                print("Opción no válida. Omitiendo película.")
                return None


def get_vsmeta_title_year(vsmeta_path):
    """
    Decodes an existing .vsmeta file and extracts the title and release year.
    """
    try:
        decoder = VsMetaDecoder()
        decoder.readVsMetaFile(vsmeta_path)
        decoder.decode()
        return decoder.info.showTitle, decoder.info.year
    except Exception:
        return None, None


def normalize_filename_if_needed(filepath, title, year, interactive=False, verbose=False):
    """
    Checks if the video filename matches the normalized title (and optional year).
    If not, renames the video file and all associated files (subtitles, .vsmeta, etc.).
    Returns the new filepath (which might be the same if no renaming occurred).
    """
    if not title:
        return filepath

    # 1. Normalize the title for the filesystem (remove characters that might cause issues in SMB/Windows)
    cleaned_title = re.sub(r'[\\/:*?"<>|]', " ", title)
    cleaned_title = " ".join(cleaned_title.split()).strip()

    # Append year if present
    if year:
        # Check if year is already in the title to avoid "Title (Year) (Year)"
        if not re.search(r'\b' + re.escape(str(year)) + r'\b', cleaned_title):
            new_base_no_ext = f"{cleaned_title} ({year})"
        else:
            new_base_no_ext = cleaned_title
    else:
        new_base_no_ext = cleaned_title

    old_dir = os.path.dirname(filepath)
    old_basename = os.path.basename(filepath)
    old_base, ext = os.path.splitext(old_basename)
    
    new_basename = new_base_no_ext + ext

    # If already matches (case-insensitive), nothing to do
    if old_base.lower() == new_base_no_ext.lower():
        if verbose:
            print(f"  [NORMALIZACIÓN] El nombre '{old_basename}' ya está normalizado.")
        return filepath

    # 2. Check for name collisions
    target_filepath = os.path.join(old_dir, new_basename)
    if os.path.exists(target_filepath) and target_filepath.lower() != filepath.lower():
        print(f"  [AVISO] No se normalizó el nombre del archivo para evitar colisión con uno existente:")
        print(f"    Existente: '{new_basename}'")
        print(f"    Conservado original: '{old_basename}'")
        return filepath

    # 3. Find associated files (subtitles, existing vsmeta, etc.)
    associated_to_rename = []
    if os.path.exists(old_dir):
        for item in os.listdir(old_dir):
            if item == old_basename:
                continue
            item_path = os.path.join(old_dir, item)
            if os.path.isfile(item_path):
                if item.startswith(old_base):
                    rest = item[len(old_base):]
                    if not rest or rest[0] in ('.', '_', '-', ' '):
                        associated_to_rename.append(item_path)

    # 4. Ask for user confirmation if interactive mode is on
    if interactive:
        print(f"\n[NORMALIZACIÓN] Se propone renombrar el video y sus archivos asociados:")
        print(f"  Origen:  '{old_basename}'")
        print(f"  Destino: '{new_basename}'")
        if associated_to_rename:
            print(f"  Archivos asociados a renombrar ({len(associated_to_rename)}):")
            for assoc in associated_to_rename:
                print(f"    - '{os.path.basename(assoc)}' -> '{new_base_no_ext}{os.path.basename(assoc)[len(old_base):]}'")
        
        choice = input("¿Confirmas el cambio de nombre? (s/n) [Defecto: s]: ").strip().lower()
        if choice == 'n':
            print("  [INFO] Renombrado omitido por el usuario.")
            return filepath

    # 5. Perform the renaming
    print(f"  [RENOMBRANDO] Normalizando nombre de archivo:")
    print(f"    Origen: '{old_basename}'")
    print(f"    Destino: '{new_basename}'")
    try:
        # Rename the main video file
        os.rename(filepath, target_filepath)
        
        # Rename associated files
        for assoc_path in associated_to_rename:
            assoc_basename = os.path.basename(assoc_path)
            assoc_ext_part = assoc_basename[len(old_base):]
            new_assoc_name = new_base_no_ext + assoc_ext_part
            new_assoc_path = os.path.join(old_dir, new_assoc_name)
            
            # Remove target if it already exists to avoid OSError
            if os.path.exists(new_assoc_path):
                try:
                    os.remove(new_assoc_path)
                except Exception:
                    pass
            os.rename(assoc_path, new_assoc_path)
            if verbose:
                print(f"    [INFO] Renombrado archivo asociado: '{assoc_basename}' -> '{new_assoc_name}'")
                
        return target_filepath
    except Exception as e:
        print(f"  [ERROR] Error al renombrar los archivos durante la normalización: {e}")
        return filepath


def process_video_file(filepath, client, force=False, interactive=False, verbose=False, normalize=False):
    """
    Deduces movie info, fetches metadata from TMDb, downloads images,
    and encodes the .vsmeta file next to the video file.
    Returns: "success", "skipped", or "failed".
    """
    # 0. Suffix cleaning and physical rename (using existing rules in rules.json)
    rules = load_cleaner_rules()
    basename = os.path.basename(filepath)
    cleaned_basename = clean_filename_with_rules(basename, rules)
    if cleaned_basename != basename:
        filepath = rename_physical_files(filepath, cleaned_basename, verbose)

    vsmeta_path = filepath + ".vsmeta"

    # Skip if exists, is valid, and force is False
    if os.path.exists(vsmeta_path) and not force and not is_vsmeta_invalid(vsmeta_path):
        if normalize:
            title, year = get_vsmeta_title_year(vsmeta_path)
            new_filepath = normalize_filename_if_needed(filepath, title, year, interactive, verbose)
            if new_filepath != filepath:
                # Touch the new video file to trigger reindexing
                try:
                    os.utime(new_filepath, None)
                except Exception:
                    pass
                return "success"
        if verbose:
            print(f"[INFO] Saltando: '{filepath}' (el archivo .vsmeta ya existe y es válido)")
        return "skipped"

    def cleanup_vsmeta():
        if os.path.exists(vsmeta_path):
            try:
                os.remove(vsmeta_path)
                print(f"  [INFO] Eliminado/Limpio archivo .vsmeta antiguo: {os.path.basename(vsmeta_path)}")
            except Exception as delete_err:
                print(f"  [ERROR] No se pudo eliminar el archivo .vsmeta: {delete_err}")

    print(f"\n[PROCESANDO] {os.path.basename(filepath)}")
    
    # 1. Parse name and year
    clean_title, year = parse_movie_filename(filepath)
    if verbose:
        print(f"  -> Título deducido: '{clean_title}', Año: {year}")

    # 2. Search TMDb (Interactive or Standard)
    if interactive:
        movie_search = query_movie_with_user(clean_title, year, client, verbose)
    else:
        movie_search = client.search_movie(clean_title, year)
        # If not found with year, try searching without year
        if not movie_search and year:
            if verbose:
                print(f"  -> No encontrado con año. Reintentando búsqueda sin año...")
            movie_search = client.search_movie(clean_title)

    if not movie_search:
        print(f"  [AVISO] No se encontró coincidencia en TMDb para '{clean_title}'")
        cleanup_vsmeta()
        return "failed"

    # 2b. If interactive mode learned a new rule, rules.json has been updated.
    # We should clean and rename the file again based on any newly saved rules!
    if interactive:
        rules = load_cleaner_rules()
        basename = os.path.basename(filepath)
        cleaned_basename = clean_filename_with_rules(basename, rules)
        if cleaned_basename != basename:
            filepath = rename_physical_files(filepath, cleaned_basename, verbose)
            vsmeta_path = filepath + ".vsmeta"

    tmdb_id = movie_search["id"]
    if verbose:
        print(f"  -> Seleccionado en TMDb: '{movie_search['title']}' (ID: {tmdb_id})")

    # 3. Fetch detailed movie info
    details = client.get_movie_details(tmdb_id)
    if not details:
        print(f"  [ERROR] No se pudieron obtener detalles para ID: {tmdb_id}")
        cleanup_vsmeta()
        return "failed"

    # 4. Map details to VsMetaInfo
    vsmeta_writer = VsMetaMovieEncoder()
    info = vsmeta_writer.info

    # Basic Info
    info.showTitle = details.get("title", "")
    info.showTitle2 = details.get("original_title", "")
    info.episodeTitle = details.get("tagline", "") or details.get("title", "")
    
    # Release Date
    release_date_str = details.get("release_date")
    if release_date_str:
        try:
            rd = date.fromisoformat(release_date_str)
            info.setEpisodeDate(rd)
        except Exception:
            pass

    info.season = 0
    info.episode = 0
    info.tvshowReleaseDate = date(1900, 1, 1)
    info.episodeLocked = True  # Default lock to prevent DS Video overwrite
    info.timestamp = int(datetime.now().timestamp())

    # Classification / certification
    info.classification = extract_certification(details.get("release_dates", {}), "ES")

    # Rating
    info.rating = details.get("vote_average", -1.0)

    # Summary
    info.chapterSummary = details.get("overview", "")

    # Credits (Cast, Directors, Writers)
    credits = details.get("credits", {})
    
    # Cast (top 15 actors)
    info.list.cast = [actor.get("name") for actor in credits.get("cast", [])[:15]]
    
    # Directors
    info.list.director = [member.get("name") for member in credits.get("crew", []) if member.get("job") == "Director"]
    
    # Writers
    info.list.writer = [member.get("name") for member in credits.get("crew", []) if member.get("job") in ("Writer", "Screenplay", "Story")]

    # Genres
    info.list.genre = [genre.get("name") for genre in details.get("genres", [])]

    # 5. Download Images directly to memory
    poster_path = details.get("poster_path")
    backdrop_path = details.get("backdrop_path")

    if poster_path:
        if verbose:
            print("  -> Descargando póster...")
        poster_bytes = client.download_image(poster_path, "w500")
        if poster_bytes:
            poster_img = VsMetaImageInfo()
            poster_img.image = poster_bytes
            info.episodeImageInfo.append(poster_img)
            info.posterImageInfo = poster_img

    if backdrop_path:
        if verbose:
            print("  -> Descargando fondo (backdrop)...")
        backdrop_bytes = client.download_image(backdrop_path, "original")
        if backdrop_bytes:
            info.backdropImageInfo.image = backdrop_bytes

    # 6. Build com.synology.TheMovieDb JSON metadata block
    imdb_id = details.get("imdb_id") or ""
    collection = details.get("belongs_to_collection")
    collection_id = collection.get("id") if collection else None

    meta_json = {
        "com.synology.TheMovieDb": {
            "reference": {
                "imdb": imdb_id,
                "themoviedb": tmdb_id
            },
            "rating": {
                "themoviedb": round(info.rating, 1)
            }
        }
    }

    if poster_path:
        meta_json["com.synology.TheMovieDb"]["poster"] = [
            f"https://image.tmdb.org/t/p/w500{poster_path}"
        ]
    if backdrop_path:
        meta_json["com.synology.TheMovieDb"]["backdrop"] = [
            f"https://image.tmdb.org/t/p/original{backdrop_path}"
        ]
    if collection_id:
        meta_json["com.synology.TheMovieDb"]["collection_id"] = {
            "themoviedb": collection_id
        }

    info.episodeMetaJson = meta_json

    # If normalize is requested, normalize the filename using TMDb title/year before writing
    if normalize:
        filepath = normalize_filename_if_needed(filepath, info.showTitle, info.year, interactive, verbose)
        vsmeta_path = filepath + ".vsmeta"

    # 7. Write .vsmeta file
    try:
        encoded_data = vsmeta_writer.encode(info)
        vsmeta_writer.writeVsMetaFile(vsmeta_path)
        print(f"  [OK] Creado: {os.path.basename(vsmeta_path)}")
        
        # Touch the video file to trigger Synology's media indexer to reload the metadata
        try:
            os.utime(filepath, None)
            if verbose:
                print(f"  -> Archivo de video tocado para forzar reindexación en Video Station.")
        except Exception as utime_err:
            if verbose:
                print(f"  [AVISO] No se pudo tocar el archivo de video: {utime_err}")
                
        return "success"
    except Exception as e:
        print(f"  [ERROR] No se pudo escribir el archivo .vsmeta: {e}")
        cleanup_vsmeta()
        return "failed"


def is_vsmeta_invalid(vsmeta_path):
    """
    Checks if a .vsmeta file is invalid (size <= 1KB or corrupt).
    """
    try:
        # Check size first (1KB or less is usually invalid or placeholder)
        if os.path.getsize(vsmeta_path) <= 1024:
            return True
        # Try to decode to verify it is not corrupt
        decoder = VsMetaDecoder()
        decoder.readVsMetaFile(vsmeta_path)
        decoder.decode()
        # If it decoded but doesn't have a show title, consider it invalid
        if not decoder.info.showTitle:
            return True
    except Exception:
        return True
    return False


# ----------------------------------------------------------------------
# 5. DIRECTORY WALK & TARGET DISPATCHER
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Generador automático de archivos .vsmeta para Synology Video Station usando la API de TMDb."
    )
    parser.add_argument(
        "target",
        help="Ruta de un archivo de video o de un directorio a escanear. Soporta rutas UNC de red."
    )
    parser.add_argument(
        "--api-key",
        default=TMDB_API_KEY,
        help="Clave API de TMDb (por defecto cargada desde .env)."
    )
    parser.add_argument(
        "--lang",
        default=TMDB_LANGUAGE,
        help="Idioma para consultar metadatos a TMDb (por defecto es-ES)."
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Fuerza la recreación del archivo .vsmeta aunque ya exista."
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Escanea subcarpetas recursivamente si se especifica un directorio como target."
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Activa el modo interactivo para refinar búsquedas dudosas o sin resultados."
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Muestra información detallada de la ejecución."
    )
    parser.add_argument(
        "--normalizar",
        action="store_true",
        help="Normaliza el nombre del archivo de video y sus asociados basándose en el título de la película en el vsmeta."
    )
    parser.add_argument(
        "--clean-invalid",
        action="store_true",
        help="Solo escanea y elimina archivos .vsmeta inválidos (tamaño <= 1KB o corruptos) y finaliza."
    )
    args = parser.parse_args()

    # Validate target exists
    target_path = os.path.abspath(args.target)
    if not os.path.exists(target_path):
        print(f"[ERROR] La ruta especificada no existe: '{args.target}'")
        sys.exit(1)

    # If clean-invalid is requested, run cleanup and exit immediately
    if args.clean_invalid:
        print(f"[LIMPIEZA] Buscando archivos .vsmeta inválidos (<= 1KB o corruptos) en: {target_path}")
        vsmeta_files = []
        if os.path.isfile(target_path):
            if target_path.lower().endswith(".vsmeta"):
                vsmeta_files.append(target_path)
            elif target_path.lower().endswith(VIDEO_EXTENSIONS):
                vsmeta_files.append(target_path + ".vsmeta")
        else:
            if args.recursive:
                ignored_folders = load_ignored_folders()
                ignored_normalized = []
                for f in ignored_folders:
                    if '/' not in f and '\\' not in f:
                        ignored_normalized.append(f.lower())
                    else:
                        ignored_normalized.append(os.path.normpath(os.path.abspath(f)).lower())
                
                for root, dirs, files in os.walk(target_path):
                    pruned_dirs = []
                    for d in dirs:
                        if d.lower() in ignored_normalized:
                            continue
                        full_path = os.path.normpath(os.path.abspath(os.path.join(root, d))).lower()
                        if full_path in ignored_normalized:
                            continue
                        pruned_dirs.append(d)
                    dirs[:] = pruned_dirs
                    
                    for file in files:
                        if file.lower().endswith(".vsmeta"):
                            vsmeta_files.append(os.path.join(root, file))
            else:
                for item in os.listdir(target_path):
                    full_path = os.path.join(target_path, item)
                    if os.path.isfile(full_path) and item.lower().endswith(".vsmeta"):
                        vsmeta_files.append(full_path)

        deleted_count = 0
        for vsmeta_path in vsmeta_files:
            if os.path.exists(vsmeta_path) and is_vsmeta_invalid(vsmeta_path):
                try:
                    size = os.path.getsize(vsmeta_path)
                    os.remove(vsmeta_path)
                    print(f"  [BORRADO] Eliminado .vsmeta inválido: '{os.path.basename(vsmeta_path)}' ({size} bytes)")
                    deleted_count += 1
                except Exception as e:
                    print(f"  [ERROR] No se pudo borrar '{vsmeta_path}': {e}")
        
        print(f"[FIN] Proceso de limpieza completado. Se eliminaron {deleted_count} archivos .vsmeta.")
        sys.exit(0)

    # Initialize client
    if not args.api_key:
        print("[ERROR] Falta la clave API de TMDb. Por favor configúrala en el archivo .env o usa la opción --api-key")
        sys.exit(1)

    client = TMDbClient(api_key=args.api_key, language=args.lang)

    video_files = []

    if os.path.isfile(target_path):
        if target_path.lower().endswith(VIDEO_EXTENSIONS):
            video_files.append(target_path)
        else:
            print(f"[ERROR] El archivo especificado no es un formato de video soportado: {args.target}")
            sys.exit(1)
    else:
        # Directory mode
        print(f"[ESCANEO] Iniciando escaneo en: {target_path}")
        if args.recursive:
            ignored_folders = load_ignored_folders()
            ignored_normalized = []
            for f in ignored_folders:
                if '/' not in f and '\\' not in f:
                    ignored_normalized.append(f.lower())
                else:
                    ignored_normalized.append(os.path.normpath(os.path.abspath(f)).lower())
            
            for root, dirs, files in os.walk(target_path):
                pruned_dirs = []
                for d in dirs:
                    if d.lower() in ignored_normalized:
                        continue
                    full_path = os.path.normpath(os.path.abspath(os.path.join(root, d))).lower()
                    if full_path in ignored_normalized:
                        continue
                    pruned_dirs.append(d)
                dirs[:] = pruned_dirs
                
                for file in files:
                    if file.lower().endswith(VIDEO_EXTENSIONS):
                        video_files.append(os.path.join(root, file))
        else:
            for item in os.listdir(target_path):
                full_path = os.path.join(target_path, item)
                if os.path.isfile(full_path) and item.lower().endswith(VIDEO_EXTENSIONS):
                    video_files.append(full_path)

        print(f"[ESCANEO] Encontrados {len(video_files)} archivos de video.")

    processed_count = 0
    success_count = 0
    skipped_count = 0
    failed_files = []

    for video_path in video_files:
        status = process_video_file(
            video_path, client, force=args.force, interactive=args.interactive, verbose=args.verbose, normalize=args.normalizar
        )
        if status == "success":
            success_count += 1
            processed_count += 1
        elif status == "skipped":
            skipped_count += 1
        else:
            failed_files.append(video_path)
            processed_count += 1

    print(f"\n[FIN] Proceso completado.")
    print(f"  - Total de videos evaluados: {len(video_files)}")
    print(f"  - Omitidos (ya tenían .vsmeta): {skipped_count}")
    print(f"  - Procesados (nuevos o forzados): {processed_count}")
    print(f"  - Creados con éxito: {success_count}")

    if failed_files:
        print(f"\n[ATENCIÓN] No se pudo generar .vsmeta para las siguientes películas ({len(failed_files)}):")
        for f in failed_files:
            clean_title, year = parse_movie_filename(f)
            print(f"  - Archivo: '{os.path.basename(f)}'")
            print(f"    Ruta:    '{f}'")
            print(f"    Buscado: '{clean_title}'" + (f" ({year})" if year else ""))
        
        # Write to failed_files.txt
        failed_txt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "failed_files.txt")
        try:
            with open(failed_txt_path, "w", encoding="utf-8") as txt_file:
                txt_file.write(f"=== Películas no resueltas ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===\n\n")
                for f in failed_files:
                    clean_title, year = parse_movie_filename(f)
                    txt_file.write(f"Archivo: {os.path.basename(f)}\n")
                    txt_file.write(f"Ruta:    {f}\n")
                    txt_file.write(f"Buscado: {clean_title}" + (f" ({year})" if year else "") + "\n")
                    txt_file.write("-" * 60 + "\n")
            print(f"\n[INFO] Se ha generado el archivo '{os.path.basename(failed_txt_path)}' con el listado de fallos.")
        except Exception as e:
            print(f"[ERROR] No se pudo escribir '{failed_txt_path}': {e}")
    else:
        # Clear old failed_files.txt if it exists to avoid confusion
        failed_txt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "failed_files.txt")
        if os.path.exists(failed_txt_path):
            try:
                os.remove(failed_txt_path)
            except Exception:
                pass

if __name__ == "__main__":
    main()
