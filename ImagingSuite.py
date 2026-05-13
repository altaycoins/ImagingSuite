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

from pathlib import Path
from contextlib import contextmanager

try:
    from rembg import remove
    from streamlit_cropper import st_cropper
except ImportError as e:
    st.error(f"A required library is missing. Please install it.\n\n{e}")
    st.stop()


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
MAX_FILE_SIZE_MB = 50

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
    'corrector': "Adjust brightness, contrast and color.",
    'watermarker': "Apply watermark to all images.",
    'enhancer': "Apply sharpening filter."
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
        st.session_state.temp_dir = tempfile.mkdtemp(
            prefix="imaging_suite_"
        )

    Path(st.session_state.temp_dir).mkdir(
        parents=True,
        exist_ok=True
    )

    return st.session_state.temp_dir


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
        'remover_results',
        'stitcher_results',
        'swapper_results',
        'splitter_results',
        'corrector_results',
        'watermarker_results',
        'enhancer_results',
        'remover_hashes',
        'stitcher_hashes',
        'splitter_hashes',
        'swapper_hashes',
        'corrector_hashes',
        'watermarker_hashes',
        'enhancer_hashes'
    ]

    for key in keys_to_clear:
        st.session_state.pop(key, None)

    cleanup_temp_dir()
    gc.collect()


def safe_open_image(file):

    try:
        file.seek(0)

        if hasattr(file, "size"):
            if file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
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

        img.save(
            path,
            format=fmt
        )

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

    if img.mode in ('RGBA', 'LA'):

        background = Image.new("RGB", img.size, "white")
        background.paste(
            img,
            mask=img.getchannel('A')
        )

        return background

    return img.convert("RGB")


def get_file_meta(base_name, suffix=""):

    fmt = st.session_state.get('global_format', 'JPEG')

    ext = "jpg" if fmt == "JPEG" else "png"

    mime = (
        "image/jpeg"
        if fmt == "JPEG"
        else "image/png"
    )

    filename = (
        f"{base_name}_{suffix}.{ext}"
        if suffix
        else f"{base_name}.{ext}"
    )

    return filename, mime, fmt


def get_download_data(img):

    fmt = st.session_state.get(
        'global_format',
        'JPEG'
    )

    img_to_save = (
        img if fmt == "PNG"
        else composite_on_white(img)
    )

    buf = io.BytesIO()

    img_to_save.save(
        buf,
        format=fmt,
        quality=95,
        optimize=True
    )

    return buf.getvalue()


def create_zip_download_button(
    processed_items,
    zip_filename_base,
    default_suffix=""
):

    if not processed_items:
        return

    temp_zip = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".zip"
    )

    with zipfile.ZipFile(
        temp_zip.name,
        "w",
        zipfile.ZIP_DEFLATED
    ) as zipf:

        for item in processed_items:

            if len(item) == 3:
                base_name, img_source, suffix = item
            else:
                base_name, img_source = item
                suffix = default_suffix

            filename, _, fmt = get_file_meta(
                base_name,
                suffix
            )

            try:

                if isinstance(img_source, str):
                    with Image.open(img_source) as img:

                        img_to_save = (
                            img if fmt == "PNG"
                            else composite_on_white(img)
                        )

                        img_bytes = io.BytesIO()

                        img_to_save.save(
                            img_bytes,
                            format=fmt,
                            quality=95,
                            optimize=True
                        )

                        zipf.writestr(
                            filename,
                            img_bytes.getvalue()
                        )

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


# =========================================================
# REMOVER
# =========================================================

def remover_logic(files):

    current_hashes = [image_hash(f) for f in files]

    if (
        st.session_state.get('remover_hashes')
        != current_hashes
    ):
        st.session_state.pop('remover_results', None)

    if (
        files
        and 'remover_results'
        not in st.session_state
    ):

        temp_dir = init_temp_dir()

        progress = st.progress(
            0,
            text="Removing backgrounds..."
        )

        processed = []

        try:

            for i, f in enumerate(files):

                progress.progress(
                    (i + 1) / len(files),
                    text=f"Processing {f.name}"
                )

                input_bytes = f.getvalue()

                if len(input_bytes) > 20 * 1024 * 1024:
                    st.warning(
                        f"{f.name} is large and may be slow."
                    )

                output_bytes = remove(input_bytes)

                img = Image.open(
                    io.BytesIO(output_bytes)
                )

                bbox = img.getbbox()

                if bbox:
                    img = img.crop(bbox)

                base, _ = os.path.splitext(f.name)

                base = sanitize_filename(base)

                temp_path = os.path.join(
                    temp_dir,
                    f"{base}_nobg.png"
                )

                safe_save_image(
                    img,
                    temp_path
                )

                processed.append({
                    "base": base,
                    "path": temp_path,
                    "file": f
                })

                img.close()

                gc.collect()

            st.session_state.remover_results = processed
            st.session_state.remover_hashes = current_hashes

            update_stats(
                'remover',
                len(files)
            )

        except Exception as e:

            st.error(f"Processing failed: {e}")

            with st.expander("Technical Details"):
                st.code(traceback.format_exc())

    if 'remover_results' in st.session_state:

        if st.button(
            "Clear Results",
            key="clear_remover"
        ):
            clear_processing_state()
            st.rerun()

        for item in st.session_state.remover_results:

            filename, mime, _ = get_file_meta(
                item['base'],
                "no-bg"
            )

            col1, col2, col3 = st.columns([2,2,1])

            original = safe_open_image(item['file'])

            if original:
                col1.image(
                    original,
                    caption="Original",
                    use_container_width=True
                )

            col2.image(
                item['path'],
                caption="Processed",
                use_container_width=True
            )

            with Image.open(item['path']) as img:
                img_data = get_download_data(img)

            col3.download_button(
                "Download",
                data=img_data,
                file_name=filename,
                mime=mime,
                key=f"download_{item['base']}"
            )

            st.divider()

        zip_items = [
            (x['base'], x['path'])
            for x in st.session_state.remover_results
        ]

        create_zip_download_button(
            zip_items,
            "removed_backgrounds",
            "no-bg"
        )


# =========================================================
# STITCHER
# =========================================================

def stitcher_logic(files):

    if len(files) % 2 != 0:
        st.warning(
            "Upload even number of images."
        )
        return

    resize_option = st.radio(
        "Resize Mode",
        [
            "Make smaller image match larger",
            "Make larger image match smaller"
        ],
        horizontal=True
    )

    pairs = [
        (files[i], files[i+1])
        for i in range(0, len(files), 2)
    ]

    if st.button(
        "Process All Pairs",
        type="primary",
        use_container_width=True
    ):

        temp_dir = init_temp_dir()

        processed = []

        try:

            for f1, f2 in pairs:

                img1 = safe_open_image(f1)
                img2 = safe_open_image(f2)

                if not img1 or not img2:
                    continue

                img1 = composite_on_white(img1)
                img2 = composite_on_white(img2)

                h1 = img1.height
                h2 = img2.height

                target_h = (
                    max(h1, h2)
                    if resize_option.startswith("Make smaller")
                    else min(h1, h2)
                )

                if img1.height != target_h:

                    img1 = img1.resize(
                        (
                            int(img1.width * target_h / h1),
                            target_h
                        ),
                        Image.Resampling.LANCZOS
                    )

                if img2.height != target_h:

                    img2 = img2.resize(
                        (
                            int(img2.width * target_h / h2),
                            target_h
                        ),
                        Image.Resampling.LANCZOS
                    )

                stitched = Image.new(
                    "RGB",
                    (
                        img1.width + img2.width,
                        target_h
                    )
                )

                stitched.paste(img1, (0,0))
                stitched.paste(img2, (img1.width,0))

                base, _ = os.path.splitext(f1.name)

                base = sanitize_filename(base)

                temp_path = os.path.join(
                    temp_dir,
                    f"{base}_stitched.png"
                )

                safe_save_image(
                    stitched,
                    temp_path
                )

                processed.append(
                    (base, temp_path)
                )

                img1.close()
                img2.close()
                stitched.close()

                gc.collect()

            st.session_state.stitcher_results = processed

            update_stats(
                'stitcher',
                len(files)
            )

        except Exception as e:

            st.error(f"Processing failed: {e}")

            with st.expander("Technical Details"):
                st.code(traceback.format_exc())

    if 'stitcher_results' in st.session_state:

        for base, path in st.session_state.stitcher_results:

            filename, mime, _ = get_file_meta(
                base,
                "stitched"
            )

            col1, col2 = st.columns([3,1])

            col1.image(
                path,
                caption=filename,
                use_container_width=True
            )

            with Image.open(path) as img:
                img_data = get_download_data(img)

            col2.download_button(
                "Download",
                data=img_data,
                file_name=filename,
                mime=mime,
                key=f"download_{base}"
            )

            st.divider()

        create_zip_download_button(
            st.session_state.stitcher_results,
            "stitched_coins",
            "stitched"
        )


# =========================================================
# CROPPER
# =========================================================

def cropper_logic(files):

    if not files:
        return

    selected = st.selectbox(
        "Choose image",
        [f.name for f in files]
    )

    file = next(
        x for x in files
        if x.name == selected
    )

    img = safe_open_image(file)

    if img is None:
        return

    aspect_ratios = {
        "Free": None,
        "1:1": (1,1),
        "16:9": (16,9),
        "4:3": (4,3),
        "3:2": (3,2)
    }

    aspect = st.selectbox(
        "Aspect Ratio",
        list(aspect_ratios.keys())
    )

    cropped = st_cropper(
        img,
        realtime_update=True,
        aspect_ratio=aspect_ratios[aspect],
        key=f"cropper_{file.name}"
    )

    st.image(
        cropped,
        caption="Cropped Result",
        use_container_width=True
    )

    base, _ = os.path.splitext(file.name)

    filename, mime, _ = get_file_meta(
        base,
        "cropped"
    )

    img_data = get_download_data(cropped)

    st.download_button(
        "⬇️ Download Cropped",
        data=img_data,
        file_name=filename,
        mime=mime,
        use_container_width=True
    )


# =========================================================
# ENHANCER
# =========================================================

def enhancer_logic(files):

    sharpness = st.slider(
        "Sharpness",
        1.0,
        5.0,
        2.0,
        0.1
    )

    if st.button(
        "Apply Enhancement",
        type="primary",
        use_container_width=True
    ):

        temp_dir = init_temp_dir()

        processed = []

        try:

            for f in files:

                img = safe_open_image(f)

                if img is None:
                    continue

                enhanced = ImageEnhance.Sharpness(
                    composite_on_white(img)
                ).enhance(sharpness)

                base, _ = os.path.splitext(f.name)

                base = sanitize_filename(base)

                temp_path = os.path.join(
                    temp_dir,
                    f"{base}_enhanced.png"
                )

                safe_save_image(
                    enhanced,
                    temp_path
                )

                processed.append(
                    (base, temp_path)
                )

                img.close()
                enhanced.close()

                gc.collect()

            st.session_state.enhancer_results = processed

            update_stats(
                'enhancer',
                len(files)
            )

        except Exception as e:

            st.error(f"Processing failed: {e}")

            with st.expander("Technical Details"):
                st.code(traceback.format_exc())

    if 'enhancer_results' in st.session_state:

        for base, path in st.session_state.enhancer_results:

            filename, mime, _ = get_file_meta(
                base,
                "enhanced"
            )

            col1, col2 = st.columns([3,1])

            col1.image(
                path,
                caption=filename,
                use_container_width=True
            )

            with Image.open(path) as img:
                img_data = get_download_data(img)

            col2.download_button(
                "Download",
                data=img_data,
                file_name=filename,
                mime=mime,
                key=f"download_{base}"
            )

        create_zip_download_button(
            st.session_state.enhancer_results,
            "enhanced_images",
            "enhanced"
        )


# =========================================================
# STATISTICS
# =========================================================

def stats_logic():

    df = get_stats()

    if df.empty:
        st.info("No statistics yet.")
        return

    total_uses = df['uses'].sum()

    total_images = df['images_processed'].sum()

    col1, col2 = st.columns(2)

    col1.metric(
        "Total Tool Executions",
        total_uses
    )

    col2.metric(
        "Images Processed",
        total_images
    )

    st.divider()

    df.columns = [
        'Tool Name',
        'Uses',
        'Images Processed'
    ]

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )


# =========================================================
# TOOL MAP
# =========================================================

tool_logic_map = {
    'remover': remover_logic,
    'stitcher': stitcher_logic,
    'cropper': cropper_logic,
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
        ["JPEG", "PNG"]
    )

    st.divider()

    if 'view' not in st.session_state:
        st.session_state.view = 'remover'

    for key, label in TOOL_PAGES.items():

        st.button(
            label,
            key=f"btn_{key}",
            use_container_width=True,
            type=(
                "primary"
                if st.session_state.view == key
                else "secondary"
            ),
            on_click=lambda k=key:
                st.session_state.update(view=k)
        )


# =========================================================
# MAIN
# =========================================================

current_view = st.session_state.get(
    'view',
    'remover'
)

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
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key=current_view
    )

    if uploaded_files:
        tool_function(uploaded_files)

else:
    tool_function()


# =========================================================
# CLEANUP
# =========================================================

atexit.register(cleanup_temp_dir)
