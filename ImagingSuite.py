import streamlit as st
from PIL import (
    Image,
    ImageEnhance,
    ImageOps,
    UnidentifiedImageError
)

import io
import os
import re
import zipfile
import tempfile
import shutil
import gc
import sqlite3
import pandas as pd
import hashlib
import traceback
import atexit
import time

from pathlib import Path
from contextlib import contextmanager

try:
    from rembg import remove
    from streamlit_cropper import st_cropper
except ImportError as e:
    st.error(f"A required library is missing. Please install it.\n\n{e}")
    st.stop()


# =========================================================
# GARBAGE COLLECTION (SERVER PROTECTION)
# =========================================================

def perform_system_garbage_collection(max_age_hours=2):
    """Scans the system temp folder and deletes any app folders older than X hours."""
    base_temp = tempfile.gettempdir()
    current_time = time.time()
    
    try:
        for item in os.listdir(base_temp):
            if item.startswith("imaging_suite_"):
                dir_path = os.path.join(base_temp, item)
                
                # Calculate how old the folder is in seconds
                folder_age_seconds = current_time - os.path.getmtime(dir_path)
                
                # If it's older than our limit, nuke it
                if folder_age_seconds > (max_age_hours * 3600):
                    shutil.rmtree(dir_path, ignore_errors=True)
    except Exception:
        pass

# Run garbage collection silently on every page load
perform_system_garbage_collection(max_age_hours=2)


# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="altaycoins Coin Imaging Suite",
    layout="centered",
    initial_sidebar_state="expanded"
)


# =========================================================
# CONSTANTS
# =========================================================

DB_FILE = "usage_stats.db"
MAX_FILE_SIZE_MB = 200

TOOL_PAGES = {
    'remover': "✨ Remover",
    'stitcher': "🧩 Stitcher",
    'splitter': "🔪 Splitter",
    'swapper': "🔄 Swapper",
    'cropper': "✂️ Cropper",
    'corrector': "🎨 Corrector",
    'watermarker': "💧 Watermarker",
    'enhancer': "🔍 Enhancer",
    'stats': "📊 Statistics"
}

TOOL_INFO = {
    'remover': "Automatically remove the background from images using AI.",
    'stitcher': "Stitch coin sides together horizontally.",
    'splitter': "Split stitched images into two separate files.",
    'swapper': "Swap the obverse and reverse sides.",
    'cropper': "Manually crop your images.",
    'corrector': "Adjust brightness, contrast, sharpness, and color.",
    'watermarker': "Apply watermark to all images.",
    'enhancer': "Apply sharpening filter.",
    'stats': "View usage statistics for the suite."
}


# =========================================================
# DATABASE
# =========================================================

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                tool_name TEXT PRIMARY KEY,
                uses INTEGER DEFAULT 0,
                images_processed INTEGER DEFAULT 0
            )
        """)

def update_stats(tool_name, num_images):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO stats(tool_name, uses, images_processed)
            VALUES (?, 1, ?)
            ON CONFLICT(tool_name)
            DO UPDATE SET
                uses = uses + 1,
                images_processed = images_processed + excluded.images_processed
        """, (tool_name, num_images))

def get_stats():
    with get_db() as conn:
        return pd.read_sql_query(
            "SELECT * FROM stats ORDER BY uses DESC",
            conn
        )

init_db()


# =========================================================
# HELPERS
# =========================================================

def sanitize_filename(name):
    name = os.path.basename(name)
    name = re.sub(r'[\\/*?:"<>|\n\r\t]', "", name)
    name = re.sub(r'\s+', '_', name)
    return name[:150]

def init_temp_dir():
    if 'temp_dir' not in st.session_state:
        st.session_state.temp_dir = tempfile.mkdtemp(prefix="imaging_suite_")
    Path(st.session_state.temp_dir).mkdir(parents=True, exist_ok=True)
    return st.session_state.temp_dir

def keep_temp_dir_alive():
    """Updates the modified time of the active temp folder so the garbage collector ignores it."""
    temp_dir = st.session_state.get('temp_dir')
    if temp_dir and os.path.exists(temp_dir):
        try:
            os.utime(temp_dir, None)
        except Exception:
            pass

def cleanup_temp_dir():
    temp_dir = st.session_state.get('temp_dir')
    if temp_dir and os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
    st.session_state.pop('temp_dir', None)

def clear_processing_state():
    keys_to_clear = [
        'remover_results', 'remover_hashes',
        'stitcher_results', 'stitcher_hashes',
        'swapper_results', 'swapper_id',
        'splitter_results', 'splitter_id',
        'corrector_results', 'corrector_hashes',
        'watermarker_results', 'watermarker_hashes',
        'enhancer_results', 'enhancer_hashes'
    ]
    for key in keys_to_clear:
        st.session_state.pop(key, None)
    cleanup_temp_dir()
    gc.collect()

def safe_open_image(file):
    try:
        file.seek(0)
        if hasattr(file, "size") and file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
            st.error(f"{file.name} exceeds {MAX_FILE_SIZE_MB}MB")
            return None
        img = Image.open(file)
        img = ImageOps.exif_transpose(img)
        return img.copy()
    except UnidentifiedImageError:
        st.error(f"Invalid image file: {file.name}")
        return None
    except Exception as e:
        st.error(f"Failed opening image {file.name}: {e}")
        return None

def safe_save_image(img, path, fmt="PNG"):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        img.save(path, format=fmt)
        return True
    except Exception as e:
        st.error(f"Failed saving image: {e}")
        return False

def image_hash(file):
    file.seek(0)
    data = file.read()
    file.seek(0)
    return hashlib.md5(data).hexdigest()

def composite_on_white(img):
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.convert('RGBA').getchannel('A'))
        return background
    return img.convert("RGB")

def get_file_meta(base_name, suffix=""):
    fmt = st.session_state.get('global_format', 'JPEG')
    ext = "jpg" if fmt == "JPEG" else "png"
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    filename = f"{base_name}_{suffix}.{ext}" if suffix else f"{base_name}.{ext}"
    return filename, mime, fmt

def get_download_data(img):
    fmt = st.session_state.get('global_format', 'JPEG')
    img_to_save = img if fmt == "PNG" else composite_on_white(img)
    buf = io.BytesIO()
    img_to_save.save(buf, format=fmt, quality=95, optimize=True)
    return buf.getvalue()

def create_zip_download_button(processed_items, zip_filename_base, default_suffix=""):
    if not processed_items: return

    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")

    with zipfile.ZipFile(temp_zip.name, "w", zipfile.ZIP_DEFLATED) as zipf:
        for item in processed_items:
            if len(item) == 3:
                base_name, img_source, suffix = item
            else:
                base_name, img_source = item
                suffix = default_suffix

            filename, _, fmt = get_file_meta(base_name, suffix)

            try:
                if isinstance(img_source, str):
                    with Image.open(img_source) as img:
                        img_to_save = img if fmt == "PNG" else composite_on_white(img)
                        img_bytes = io.BytesIO()
                        img_to_save.save(img_bytes, format=fmt, quality=95, optimize=True)
                        zipf.writestr(filename, img_bytes.getvalue())
                elif isinstance(img_source, Image.Image):
                    img_to_save = img_source if fmt == "PNG" else composite_on_white(img_source)
                    img_bytes = io.BytesIO()
                    img_to_save.save(img_bytes, format=fmt, quality=95, optimize=True)
                    zipf.writestr(filename, img_bytes.getvalue())
            except Exception as e:
                st.error(f"ZIP error: {e}")

    with open(temp_zip.name, "rb") as f:
        st.download_button(
            label="📦 Download All as ZIP",
            data=f.read(),
            file_name=f"{zip_filename_base}.zip",
            mime="application/zip",
            use_container_width=True
        )

    try:
        os.unlink(temp_zip.name)
    except Exception:
        pass

def info_box(text):
    st.markdown(
        f"""
        <div style="
            background-color:#e6f3ff;
            border-left:5px solid #0066cc;
            padding:10px;
            border-radius:5px;
            margin-bottom:1rem;
        ">
        {text}
        </div>
        """,
        unsafe_allow_html=True
    )

def debug_temp_storage():
    st.divider()
    st.subheader("🛠️ System Storage Monitor")
    base_temp = tempfile.gettempdir()
    app_temps = [d for d in os.listdir(base_temp) if d.startswith("imaging_suite_")]
    
    if not app_temps:
        st.success("The temp folder is perfectly clean. No orphaned files!")
        return
        
    st.warning(f"Found {len(app_temps)} active temp folders.")
    for d in app_temps:
        full_path = os.path.join(base_temp, d)
        try:
            total_size = sum(
                os.path.getsize(os.path.join(dirpath, filename)) 
                for dirpath, _, filenames in os.walk(full_path) 
                for filename in filenames
            )
            st.code(f"{d}  ->  {total_size / (1024 * 1024):.2f} MB")
        except Exception as e:
            st.error(f"Could not read {d}: {e}")
            
    if st.button("Force Clean System Temp", type="primary"):
        for d in app_temps:
            try:
                shutil.rmtree(os.path.join(base_temp, d), ignore_errors=True)
            except Exception:
                pass
        st.rerun() 


# =========================================================
# REMOVER
# =========================================================

def remover_logic(files):
    current_hashes = [image_hash(f) for f in files]

    if st.session_state.get('remover_hashes') != current_hashes:
        st.session_state.pop('remover_results', None)

    if files and 'remover_results' not in st.session_state:
        temp_dir = init_temp_dir()
        progress = st.progress(0, text="Removing backgrounds...")
        processed = []

        try:
            for i, f in enumerate(files):
                progress.progress((i + 1) / len(files), text=f"Processing {f.name}")
                input_bytes = f.getvalue()

                if len(input_bytes) > 20 * 1024 * 1024:
                    st.warning(f"{f.name} is large and may be slow.")

                output_bytes = remove(input_bytes)
                img = Image.open(io.BytesIO(output_bytes))
                
                def get_clean_bbox(im, threshold=20):
                    alpha = im.split()[-1]
                    return alpha.point(lambda p: p if p > threshold else 0).getbbox()

                bbox = get_clean_bbox(img)
                if bbox:
                    cropped_full = img.crop(bbox)
                    w, h = cropped_full.size
                    
                    if w > h * 1.3:
                        mid = w // 2
                        left_side = cropped_full.crop((0, 0, mid, h))
                        right_side = cropped_full.crop((mid, 0, w, h))
                        
                        left_bbox = get_clean_bbox(left_side)
                        right_bbox = get_clean_bbox(right_side)
                        
                        if left_bbox and right_bbox:
                            left_side = left_side.crop(left_bbox)
                            right_side = right_side.crop(right_bbox)
                            target_h = min(left_side.height, right_side.height)
                            
                            if left_side.height != target_h:
                                left_side = left_side.resize((int(left_side.width * target_h / left_side.height), target_h), Image.Resampling.LANCZOS)
                            if right_side.height != target_h:
                                right_side = right_side.resize((int(right_side.width * target_h / right_side.height), target_h), Image.Resampling.LANCZOS)
                            
                            stitched = Image.new("RGBA", (left_side.width + right_side.width, target_h))
                            stitched.paste(left_side, (0, 0))
                            stitched.paste(right_side, (left_side.width, 0))
                            img = stitched
                        elif left_bbox:
                            img = left_side.crop(left_bbox)
                        elif right_bbox:
                            img = right_side.crop(right_bbox)
                        else:
                            img = cropped_full
                    else:
                        img = cropped_full

                base, _ = os.path.splitext(f.name)
                base = sanitize_filename(base)
                temp_path = os.path.join(temp_dir, f"{base}_nobg.png")
                safe_save_image(img, temp_path)

                processed.append({"base": base, "path": temp_path, "file": f})
                img.close()
                gc.collect()

            st.session_state.remover_results = processed
            st.session_state.remover_hashes = current_hashes
            update_stats('remover', len(files))

        except Exception as e:
            st.error(f"Processing failed: {e}")

    if 'remover_results' in st.session_state:
        if st.button("Clear Results", key="clear_remover"):
            clear_processing_state()
            st.rerun()

        for item in st.session_state.remover_results:
            filename, mime, _ = get_file_meta(item['base'], "no-bg")
            col1, col2, col3 = st.columns([2,2,1])
            original = safe_open_image(item['file'])

            if original:
                col1.image(original, caption="Original", use_container_width=True)
            col2.image(item['path'], caption="Processed", use_container_width=True)

            with Image.open(item['path']) as img:
                img_data = get_download_data(img)
            col3.download_button("Download", data=img_data, file_name=filename, mime=mime, key=f"download_{item['base']}")
            st.divider()

        zip_items = [(x['base'], x['path']) for x in st.session_state.remover_results]
        create_zip_download_button(zip_items, "removed_backgrounds", "no-bg")


# =========================================================
# STITCHER
# =========================================================

def stitcher_logic(files):
    if len(files) % 2 != 0:
        st.warning("Upload an even number of images.")
        return

    files.sort(key=lambda f: f.name)
    resize_option = st.radio("Resize Mode", ["Make smaller image match larger", "Make larger image match smaller"], index=1, horizontal=True)
    pairs = [(files[i], files[i+1]) for i in range(0, len(files), 2)]
    
    st.write("### Image Pairs Preview")
    for i, (f1, f2) in enumerate(pairs):
        c1, c2 = st.columns(2)
        c1.image(f1, caption=f1.name, use_container_width=True)
        c2.image(f2, caption=f2.name, use_container_width=True)
    st.divider()

    if st.button("Process All Pairs", type="primary", use_container_width=True):
        temp_dir = init_temp_dir()
        processed = []

        try:
            for f1, f2 in pairs:
                img1 = composite_on_white(safe_open_image(f1))
                img2 = composite_on_white(safe_open_image(f2))

                if not img1 or not img2: continue

                h1, h2 = img1.height, img2.height
                target_h = max(h1, h2) if resize_option.startswith("Make smaller") else min(h1, h2)

                if img1.height != target_h:
                    img1 = img1.resize((int(img1.width * target_h / h1), target_h), Image.Resampling.LANCZOS)
                if img2.height != target_h:
                    img2 = img2.resize((int(img2.width * target_h / h2), target_h), Image.Resampling.LANCZOS)

                stitched = Image.new("RGB", (img1.width + img2.width, target_h))
                stitched.paste(img1, (0,0))
                stitched.paste(img2, (img1.width,0))

                base, _ = os.path.splitext(f1.name)
                base = sanitize_filename(base)
                temp_path = os.path.join(temp_dir, f"{base}_stitched.png")
                safe_save_image(stitched, temp_path)

                processed.append((base, temp_path))
                img1.close(); img2.close(); stitched.close()
                gc.collect()

            st.session_state.stitcher_results = processed
            update_stats('stitcher', len(files))

        except Exception as e:
            st.error(f"Processing failed: {e}")

    if 'stitcher_results' in st.session_state:
        for base, path in st.session_state.stitcher_results:
            filename, mime, _ = get_file_meta(base, "stitched")
            col1, col2 = st.columns([3,1])
            col1.image(path, caption=filename, use_container_width=True)
            with Image.open(path) as img:
                img_data = get_download_data(img)
            col2.download_button("Download", data=img_data, file_name=filename, mime=mime, key=f"download_{base}")
            st.divider()

        create_zip_download_button(st.session_state.stitcher_results, "stitched_coins", "stitched")


# =========================================================
# SPLITTER
# =========================================================

def splitter_logic(files):
    def _run_split(idx):
        item = st.session_state.splitter_results[idx]
        slider_key = item['file_ref'].file_id
        mid = st.session_state[slider_key]
        image = item['original']
        w, h = image.size
        
        st.session_state.splitter_results[idx]['processed_a'] = image.crop((0, 0, mid, h))
        st.session_state.splitter_results[idx]['processed_b'] = image.crop((mid, 0, w, h))

    current_files_id = [f.file_id for f in files] if files else None

    if 'splitter_id' in st.session_state and st.session_state.splitter_id != current_files_id:
        st.session_state.pop('splitter_results', None)
        st.session_state.pop('splitter_id', None)

    if files and 'splitter_results' not in st.session_state:
        processed_images = []
        for f in files:
            image = safe_open_image(f)
            if not image: continue
            
            base = sanitize_filename(os.path.splitext(f.name)[0])
            w, h = image.size
            mid = w // 2

            processed_images.append({
                'original': image,
                'processed_a': image.crop((0, 0, mid, h)),
                'processed_b': image.crop((mid, 0, w, h)), 
                'base_name': base,
                'file_ref': f
            })
            
        st.session_state.splitter_results = processed_images
        st.session_state.splitter_id = current_files_id
        update_stats('splitter', len(files))

    if 'splitter_results' in st.session_state:
        st.subheader("Interactive Splitter Results")
        if st.button("Clear Results", key="clear_splitter"):
            st.session_state.pop('splitter_results', None)
            st.session_state.pop('splitter_id', None)
            st.rerun()

        for idx, item in enumerate(st.session_state.splitter_results):
            original = item['original']
            part_a = item['processed_a'] 
            part_b = item['processed_b'] 
            base = item['base_name']
            w, h = original.size
            
            filename_a, mime_a, _ = get_file_meta(base, "a")
            filename_b, mime_b, _ = get_file_meta(base, "b")
            
            st.write(f"**Processing:** `{base}`")
            st.slider("Adjust split point", 1, w - 1, w // 2, key=item['file_ref'].file_id, on_change=_run_split, args=(idx,))
            
            st.image(original, caption="Original", use_container_width=True)
            col1, col2 = st.columns(2)
            with col1:
                st.image(part_a, caption=filename_a, use_container_width=True)
                st.download_button(f"Download A", data=get_download_data(part_a), file_name=filename_a, mime=mime_a, use_container_width=True, key=f"download_a_{base}")
            with col2:
                st.image(part_b, caption=filename_b, use_container_width=True)
                st.download_button(f"Download B", data=get_download_data(part_b), file_name=filename_b, mime=mime_b, use_container_width=True, key=f"download_b_{base}")
            st.divider()
            
        final_processed = []
        for item in st.session_state.splitter_results:
            if item['processed_a']: final_processed.append((item['base_name'], item['processed_a'], "a"))
            if item['processed_b']: final_processed.append((item['base_name'], item['processed_b'], "b"))
        create_zip_download_button(final_processed, "split_coins")


# =========================================================
# SWAPPER
# =========================================================

def swapper_logic(files):
    def _run_swap(idx):
        item = st.session_state.swapper_results[idx]
        slider_key = item['file_ref'].file_id
        mid = st.session_state[slider_key]
        image = item['original']
        w, h = image.size
        
        obv, rev = image.crop((0, 0, mid, h)), image.crop((mid, 0, w, h))
        new_img = Image.new("RGB", (w, h), color='white')
        new_img.paste(rev, (0, 0), rev if 'A' in rev.getbands() else None)
        new_img.paste(obv, (rev.width, 0), obv if 'A' in obv.getbands() else None)
        st.session_state.swapper_results[idx]['processed'] = new_img

    current_files_id = [f.file_id for f in files] if files else None

    if 'swapper_id' in st.session_state and st.session_state.swapper_id != current_files_id:
        st.session_state.pop('swapper_results', None)
        st.session_state.pop('swapper_id', None)

    if files and 'swapper_results' not in st.session_state:
        processed_images = []
        for f in files:
            image = safe_open_image(f)
            if not image: continue

            base = sanitize_filename(os.path.splitext(f.name)[0])
            w, h = image.size
            mid = w // 2
            obv, rev = image.crop((0, 0, mid, h)), image.crop((mid, 0, w, h))
            
            new_img = Image.new("RGB", (w, h), color='white')
            new_img.paste(rev, (0, 0), rev if 'A' in rev.getbands() else None)
            new_img.paste(obv, (rev.width, 0), obv if 'A' in obv.getbands() else None)

            processed_images.append({
                'original': image, 
                'processed': new_img,
                'base_name': base, 
                'file_ref': f
            })
            
        st.session_state.swapper_results = processed_images
        st.session_state.swapper_id = current_files_id
        update_stats('swapper', len(files))

    if 'swapper_results' in st.session_state:
        st.subheader("Interactive Swapper Results")
        if st.button("Clear Results", key="clear_swapper"):
            st.session_state.pop('swapper_results', None)
            st.session_state.pop('swapper_id', None)
            st.rerun()

        for idx, item in enumerate(st.session_state.swapper_results):
            image = item['original']
            processed = item['processed'] 
            base = item['base_name']
            w, h = image.size
            
            filename, mime, _ = get_file_meta(base, "swapped")
            st.write(f"**Processing:** `{base}`")
            st.slider("Adjust split point", 1, w - 1, w // 2, key=item['file_ref'].file_id, on_change=_run_swap, args=(idx,))
            
            col1, col2, col3 = st.columns([2, 2, 1])
            col1.image(image, caption="Original", use_container_width=True) 
            col2.image(processed, caption="Swapped", use_container_width=True)
            col3.download_button("Download", data=get_download_data(processed), file_name=filename, mime=mime, key=f"download_{base}")
            st.divider()
            
        final_processed = [(item['base_name'], item['processed']) for item in st.session_state.swapper_results if item['processed']]
        create_zip_download_button(final_processed, "swapped_coins", "swapped")


# =========================================================
# CROPPER
# =========================================================

def cropper_logic(files):
    if not files: return
    selected = st.selectbox("Choose image", [f.name for f in files])
    file = next(x for x in files if x.name == selected)
    img = safe_open_image(file)

    if img is None: return

    aspect_ratios = {"Free": None, "1:1": (1,1), "16:9": (16,9), "4:3": (4,3), "3:2": (3,2), "9:16": (9,16), "3:4": (3,4), "2:3": (2,3)}
    aspect = st.selectbox("Aspect Ratio", list(aspect_ratios.keys()))
    st.info("Drag the corners of the box to crop your image.")

    cropped = st_cropper(img, realtime_update=True, aspect_ratio=aspect_ratios[aspect], key=f"cropper_{file.name}")
    st.image(cropped, caption="Cropped Result", use_container_width=True)
    
    base, _ = os.path.splitext(file.name)
    filename, mime, _ = get_file_meta(base, "cropped")
    st.download_button("⬇️ Download Cropped", data=get_download_data(cropped), file_name=filename, mime=mime, use_container_width=True)


# =========================================================
# CORRECTOR
# =========================================================

def corrector_logic(files):
    st.subheader("Correction Settings")
    brightness = st.slider("Brightness", 0.5, 1.5, 1.0)
    contrast = st.slider("Contrast", 0.5, 1.5, 1.0)
    sharpness = st.slider("Sharpness", 0.0, 3.0, 1.0)
    saturation = st.slider("Saturation (Color)", 0.0, 2.0, 1.0)

    if st.button("Apply Corrections", type="primary", use_container_width=True):
        temp_dir = init_temp_dir()
        processed = []

        try:
            for f in files:
                img = safe_open_image(f)
                if img is None: continue

                corrected = composite_on_white(img)
                corrected = ImageEnhance.Brightness(corrected).enhance(brightness)
                corrected = ImageEnhance.Contrast(corrected).enhance(contrast)
                corrected = ImageEnhance.Sharpness(corrected).enhance(sharpness)
                corrected = ImageEnhance.Color(corrected).enhance(saturation)

                base = sanitize_filename(os.path.splitext(f.name)[0])
                temp_path = os.path.join(temp_dir, f"{base}_corrected.png")
                safe_save_image(corrected, temp_path)
                
                processed.append((base, temp_path))
                img.close(); corrected.close()
                gc.collect()

            st.session_state.corrector_results = processed
            update_stats('corrector', len(files))

        except Exception as e:
            st.error(f"Processing failed: {e}")

    if 'corrector_results' in st.session_state:
        for base, path in st.session_state.corrector_results:
            filename, mime, _ = get_file_meta(base, "corrected")
            col1, col2 = st.columns([3,1])
            col1.image(path, caption=filename, use_container_width=True)
            with Image.open(path) as img:
                col2.download_button("Download", data=get_download_data(img), file_name=filename, mime=mime, key=f"download_{base}")

        create_zip_download_button(st.session_state.corrector_results, "corrected_images", "corrected")


# =========================================================
# WATERMARKER
# =========================================================

def watermarker_logic(files):
    st.subheader("Watermark Settings")
    watermark_file = st.file_uploader("Upload watermark (PNG)", type=["png"])

    if watermark_file:
        watermark_img = Image.open(watermark_file).convert("RGBA")
        pos_map = {"Center": (0.5, 0.5), "Top Left": (0, 0), "Top Right": (1, 0), "Bottom Left": (0, 1), "Bottom Right": (1, 1)}
        
        c1, c2, c3 = st.columns(3)
        pos = c1.selectbox("Position", list(pos_map.keys()))
        scale = c2.slider("Scale %", 10, 100, 25)
        opacity = c3.slider("Opacity %", 0, 100, 50)

        if st.button("Apply Watermark", type="primary", use_container_width=True):
            temp_dir = init_temp_dir()
            processed = []

            try:
                for f in files:
                    original = safe_open_image(f)
                    if original is None: continue
                    
                    original = original.convert("RGBA")
                    wm_w, wm_h = watermark_img.size
                    base_w = int(original.width * (scale / 100))
                    wm_resized = watermark_img.resize((base_w, int(wm_h * base_w / wm_w)), Image.Resampling.LANCZOS)
                    
                    if opacity < 100:
                        alpha = wm_resized.split()[3]
                        alpha = ImageEnhance.Brightness(alpha).enhance(opacity / 100)
                        wm_resized.putalpha(alpha)
                        
                    px, py = pos_map[pos]
                    pos_x = int(original.width * px - wm_resized.width * px)
                    pos_y = int(original.height * py - wm_resized.height * py)
                    
                    transparent = Image.new('RGBA', original.size, (0,0,0,0))
                    transparent.paste(original, (0,0))
                    transparent.paste(wm_resized, (pos_x, pos_y), mask=wm_resized)

                    base = sanitize_filename(os.path.splitext(f.name)[0])
                    temp_path = os.path.join(temp_dir, f"{base}_watermarked.png")
                    safe_save_image(transparent, temp_path)
                    
                    processed.append((base, temp_path))
                    original.close(); transparent.close()
                    gc.collect()

                st.session_state.watermarker_results = processed
                update_stats('watermarker', len(files))

            except Exception as e:
                st.error(f"Processing failed: {e}")

    if 'watermarker_results' in st.session_state:
        for base, path in st.session_state.watermarker_results:
            filename, mime, _ = get_file_meta(base, "watermarked")
            col1, col2 = st.columns([3,1])
            col1.image(path, caption=filename, use_container_width=True)
            with Image.open(path) as img:
                col2.download_button("Download", data=get_download_data(img), file_name=filename, mime=mime, key=f"download_{base}")

        create_zip_download_button(st.session_state.watermarker_results, "watermarked_images", "watermarked")


# =========================================================
# ENHANCER
# =========================================================

def enhancer_logic(files):
    sharpness = st.slider("Sharpness", 1.0, 5.0, 2.0, 0.1)

    if st.button("Apply Enhancement", type="primary", use_container_width=True):
        temp_dir = init_temp_dir()
        processed = []

        try:
            for f in files:
                img = safe_open_image(f)
                if img is None: continue

                enhanced = ImageEnhance.Sharpness(composite_on_white(img)).enhance(sharpness)
                base = sanitize_filename(os.path.splitext(f.name)[0])
                temp_path = os.path.join(temp_dir, f"{base}_enhanced.png")
                safe_save_image(enhanced, temp_path)
                
                processed.append((base, temp_path))
                img.close(); enhanced.close()
                gc.collect()

            st.session_state.enhancer_results = processed
            update_stats('enhancer', len(files))

        except Exception as e:
            st.error(f"Processing failed: {e}")

    if 'enhancer_results' in st.session_state:
        for base, path in st.session_state.enhancer_results:
            filename, mime, _ = get_file_meta(base, "enhanced")
            col1, col2 = st.columns([3,1])
            col1.image(path, caption=filename, use_container_width=True)
            with Image.open(path) as img:
                col2.download_button("Download", data=get_download_data(img), file_name=filename, mime=mime, key=f"download_{base}")

        create_zip_download_button(st.session_state.enhancer_results, "enhanced_images", "enhanced")


# =========================================================
# STATISTICS
# =========================================================

def stats_logic():
    df = get_stats()
    if df.empty:
        st.info("No statistics yet.")
    else:
        total_uses = df['uses'].sum()
        total_images = df['images_processed'].sum()

        col1, col2 = st.columns(2)
        col1.metric("Total Tool Executions", total_uses)
        col2.metric("Images Processed", total_images)
        st.divider()

        df.columns = ['Tool Name', 'Uses', 'Images Processed']
        st.dataframe(df, use_container_width=True, hide_index=True)
        
    debug_temp_storage()


# =========================================================
# TOOL MAP
# =========================================================

tool_logic_map = {
    'remover': remover_logic,
    'stitcher': stitcher_logic,
    'splitter': splitter_logic,
    'swapper': swapper_logic,
    'cropper': cropper_logic,
    'corrector': corrector_logic,
    'watermarker': watermarker_logic,
    'enhancer': enhancer_logic,
    'stats': stats_logic
}


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:
    logo_path = "logo.png"
    if os.path.exists(logo_path):
        st.image(logo_path)
    st.divider()

    st.session_state.global_format = st.selectbox(
        "Download Format",
        ["JPEG", "PNG"],
        format_func=lambda x: "PNG (Supports Transparency)" if x == "PNG" else "JPG (Composited on White)"
    )
    st.divider()

    if 'view' not in st.session_state:
        st.session_state.view = 'remover'

    for key, label in TOOL_PAGES.items():
        st.button(
            label,
            key=f"btn_{key}",
            use_container_width=True,
            type="primary" if st.session_state.view == key else "secondary",
            on_click=lambda k=key: st.session_state.update(view=k)
        )


# =========================================================
# MAIN
# =========================================================

current_view = st.session_state.get('view', 'remover')

if st.session_state.get('last_view') != current_view:
    clear_processing_state()

st.session_state.last_view = current_view
st.title(TOOL_PAGES[current_view])

if current_view in TOOL_INFO:
    info_box(TOOL_INFO[current_view])

tool_function = tool_logic_map[current_view]

if current_view != 'stats':
    uploaded_files = st.file_uploader(
        "Upload Images",
        type=["jpg", "jpeg", "png", "webp", "tiff", "tif"], 
        accept_multiple_files=True,
        key=current_view
    )
    if uploaded_files:
        tool_function(uploaded_files)
        keep_temp_dir_alive()
else:
    tool_function()
    keep_temp_dir_alive()


# =========================================================
# CLEANUP
# =========================================================

atexit.register(cleanup_temp_dir)