"""The page shoppers use. Start everything with:  python -m scripts.run_app

This page only talks to the API (ui/api_client.py). All flags and rankings come from the API.
Everything the shopper reads is in everyday words: no "rules", "flags" or "tables"."""
import html
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # so "ui" and "app" can be imported

import streamlit as st  # noqa: E402

from ui import api_client  # noqa: E402
from ui.logic import (MAX_CONCERNS, MAX_PRODUCTS, METHODS, MIN_PRODUCTS, REASON_LABELS,  # noqa: E402
                      SOURCE_LABELS, UI_VERSION, build_request, problems, tip_for)

DISCLAIMER = ("This is general information about ingredients, not medical advice. Patch test new products "
              "and talk to a dermatologist or doctor about skin or scalp conditions.")

st.set_page_config(page_title="Compare skincare and haircare products", page_icon="🧴", layout="centered")
st.markdown(f"<style>{(Path(__file__).parent / 'style.css').read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True)
api = api_client.make_client()
ss = st.session_state
esc = html.escape


def step(n: int, title: str):
    st.markdown(f'<h2><span class="step">{n}</span>{esc(title)}</h2>', unsafe_allow_html=True)


# ---------------- helpers ----------------

def new_product() -> dict:
    return {"id": uuid.uuid4().hex[:8]}


if "products" not in ss:
    ss.products = [new_product() for _ in range(MIN_PRODUCTS)]


def field(pid: str, name: str, default=None):
    return ss.get(f"{name}_{pid}", default)


def read_product(p: dict) -> dict:
    pid = p["id"]
    picked = field(pid, "picked", None)
    picked_name = next((r["display"] for r in field(pid, "search", []) if r["barcode"] == picked), "")
    return {"method": field(pid, "method", METHODS[0]),
            "barcode": field(pid, "barcode", ""), "found_name": field(pid, "found_name", ""),
            "found_barcode": field(pid, "found_barcode", ""), "picked_barcode": picked, "picked_name": picked_name,
            "pasted": field(pid, "pasted", ""), "extracted": field(pid, "extracted", "")}


def sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


def short_label(label: str) -> str:
    """'Contains ingredients commonly used for frizz' -> 'commonly used for frizz'."""
    for prefix in ("Contains ingredients commonly used for", "Contains ingredients"):
        if label.startswith(prefix):
            return "commonly used for" + label[len("Contains ingredients commonly used for"):] \
                if prefix.endswith("for") else label[len(prefix):].strip()
    return label[:1].lower() + label[1:]


def product_label(r: dict) -> str:
    return " ".join(x for x in (r.get("brand"), r.get("product_name")) if x)


def queue(kind: str, pid: str):
    """Widget callbacks only note what to do. The slow call then runs in the page itself, right on the
    product card, so a spinner with a message shows exactly where you're looking instead of the whole
    page going grey with no explanation."""
    ss[f"todo_{kind}_{pid}"] = True


def run_queued(kind: str, pid: str, work, message: str):
    if ss.pop(f"todo_{kind}_{pid}", False):
        with st.spinner(message):
            work(pid)


def do_lookup(pid: str):
    bc = (field(pid, "barcode", "") or "").strip()
    try:
        r = api.lookup_barcode(bc)["results"][0]
        ss[f"found_name_{pid}"], ss[f"found_barcode_{pid}"] = product_label(r), bc
        name = product_label(r) or "a product"
        ss[f"lookup_msg_{pid}"] = ("ok" if r["has_ingredients"] else "warn",
                                   f"Found {name}." + ("" if r["has_ingredients"] else
                                                       " It has no ingredient list, so try pasting or a photo."))
    except api_client.ApiProblem as e:
        ss[f"lookup_msg_{pid}"] = ("warn", e.message)


def do_search(pid: str):
    q = (field(pid, "query", "") or "").strip()
    ss[f"picked_{pid}"] = None
    if not q:
        ss[f"search_{pid}"], ss[f"search_msg_{pid}"] = [], "Type a product name first."
        return
    try:
        ss[f"search_{pid}"] = [{**r, "display": product_label(r)} for r in api.search(q)["results"]]
        ss[f"search_msg_{pid}"] = ""
    except api_client.ApiProblem as e:
        ss[f"search_{pid}"], ss[f"search_msg_{pid}"] = [], e.message


@st.cache_resource
def _workers() -> ThreadPoolExecutor:
    """Helper threads that read photos in the background. Shared by the whole page, made once."""
    return ThreadPoolExecutor(max_workers=4)


def start_photo_read(pid: str):
    """Hand the photo to a helper thread and remember the job in session state. The job keeps going
    even if the page reruns meanwhile (for example when you click something else), so a reading is
    never lost half-way."""
    up = field(pid, "photo")
    if up is None:                                   # the photo was removed: clear what was read from it
        ss[f"extract_msg_{pid}"] = None
        ss[f"extracted_{pid}"] = None
        ss.pop(f"job_{pid}", None)
        ss.pop(f"read_file_{pid}", None)
        return
    if ss.get(f"read_file_{pid}") == up.file_id:     # this exact upload was already read (or is being read)
        return
    ss[f"read_file_{pid}"] = up.file_id
    progress_id = uuid.uuid4().hex
    ss[f"extract_msg_{pid}"] = None
    ss[f"job_{pid}"] = (_workers().submit(api.extract, up.getvalue(), up.name, up.type or "image/jpeg", progress_id),
                        progress_id)


@st.fragment(run_every=1.0)
def photo_status(pid: str, category: str | None = None):
    """Shown under the uploader while a photo is being read. Checks once a second, says which reader is
    trying, and as soon as the answer arrives, puts it on the page (no click needed)."""
    job = ss.get(f"job_{pid}")
    if not job:
        return
    future, progress_id = job
    if not future.done():
        p = api.extract_progress(progress_id)
        step = f" Trying {p['reader']} ({p['n']} of {p['of']})..." if p.get("reader") else ""
        with st.container(key=f"reading_{pid}"):
            st.markdown(":material/directions_run: Reading your photo..." + step.replace("*", ""))
            st.caption("While you wait: " + tip_for(category, time.time()))
        return
    ss.pop(f"job_{pid}", None)
    try:
        apply_photo_result(pid, future.result())
    except api_client.ApiProblem as e:
        ss[f"extract_msg_{pid}"] = ("warn", e.message)
    except Exception:
        ss[f"extract_msg_{pid}"] = ("warn", "Something went wrong while reading the photo. Please try again, "
                                            "or paste the ingredient list.")
    st.rerun()                                       # show the result and update the Compare button


def apply_photo_result(pid: str, r: dict):
    ss[f"extracted_{pid}"] = r.get("ingredients_text", "")
    reader = f" Read by {r['reader_label']}." if r.get("reader_label") else ""
    if r.get("readable") and r.get("possibly_incomplete"):
        ss[f"extract_msg_{pid}"] = ("warn", "This ingredient list may be incomplete ("
                                    + (r.get("incomplete_reason") or "it looks cut short")
                                    + "). Compare it with the label and add anything missing below, or paste the "
                                    "full list instead. Tip: a photo of just the ingredient list, straight on and "
                                    "in good light, reads best." + reader)
    elif r.get("readable"):
        note = f" ({r['confidence_note']})" if r.get("confidence_note") else ""
        offline = r.get("reader") == "offline_ocr"          # no AI: more mistakes, so shown as a caution
        ss[f"extract_msg_{pid}"] = ("warn" if offline else "ok",
                                    "Please check this text matches the label, and fix anything wrong." + note + reader)
    else:
        ss[f"extract_msg_{pid}"] = ("warn", "We couldn't read an ingredient list in that photo. "
                                    + (r.get("confidence_note") or "Try a sharper photo, or paste the list."))


def add_product():
    if len(ss.products) < MAX_PRODUCTS:
        ss.products.append(new_product())


def remove_product(pid: str):
    if len(ss.products) > MIN_PRODUCTS:
        ss.products = [p for p in ss.products if p["id"] != pid]


def show_msg(msg):
    if msg:
        kind, text = msg
        (st.success if kind == "ok" else st.warning)(text)


# ---------------- page ----------------

st.markdown(
    '<div class="hero"><div class="spark">✦</div><h1>Compare skincare and haircare products</h1>'
    "<p>Pick a product type and your concerns, add 2 to 4 products of that type, and see which may suit you "
    "better, with the reason and source behind every point.</p>"
    f'<p class="version">Version {UI_VERSION}</p></div>', unsafe_allow_html=True)
st.caption(DISCLAIMER)

try:
    if "options" not in ss:                          # the list of types and concerns never changes while you use the page
        ss.options = api.options()
    options = ss.options
except api_client.ApiProblem as e:
    st.error(e.message)
    st.info("To start everything, run this in the project folder:  python -m scripts.run_app")
    st.stop()

types = {t["id"]: t for t in options["product_types"]}

step(1, "Product type")
ptype = st.selectbox("What kind of product are you comparing?", list(types), index=None,
                     format_func=lambda t: types[t]["label"], placeholder="Choose a product type", key="ptype")

concerns = []
profile = {}
if ptype:
    t = types[ptype]
    step(2, "Your concerns")
    labels = {c["id"]: c["label"] for c in t["concerns"]}
    concerns = st.multiselect(f"Choose 1 to {MAX_CONCERNS} concerns", list(labels), format_func=labels.get,
                              max_selections=MAX_CONCERNS, key=f"concerns_{ptype}",
                              placeholder="Choose concerns")
    st.caption("We only list concerns we have trusted sources for, for this kind of product.")

    step(3, "About you")
    po = options["profile_options"]
    if t["category"] == "skin":
        profile["skin_type"] = st.selectbox("Skin type (optional)", po["skin_type"], index=None, key="skin_type",
                                            placeholder="Choose if you like")
    else:
        profile["scalp_type"] = st.selectbox("Scalp type (optional)", po["scalp_type"], index=None, key="scalp_type",
                                             placeholder="Choose if you like")
    profile["sensitive"] = st.checkbox("My skin or scalp is sensitive", key="sensitive")
    profile["avoid_fragrance"] = st.checkbox("I prefer to avoid fragrance", key="avoid_fragrance")

    step(4, "Products")
    st.caption(f"Add {MIN_PRODUCTS} to {MAX_PRODUCTS} products. They must all be {t['label'].lower()} products.")
    for i, p in enumerate(ss.products, start=1):
        pid = p["id"]
        with st.container(border=True, key=f"card_{pid}"):
            st.subheader(f"Product {i}")
            method = st.radio("How do you want to add it?", METHODS, key=f"method_{pid}", horizontal=True)
            if method == "Barcode":
                st.text_input("Barcode (the numbers under the stripes, then press Enter)", key=f"barcode_{pid}",
                              on_change=queue, args=("lookup", pid))
                run_queued("lookup", pid, do_lookup, "Looking up the barcode...")
                show_msg(field(pid, "lookup_msg"))
            elif method == "Search by name":
                st.text_input("Product name (press Enter to search)", key=f"query_{pid}", on_change=queue,
                              args=("search", pid))
                run_queued("search", pid, do_search, "Searching the product database...")
                results = field(pid, "search", [])
                if field(pid, "search_msg"):
                    st.warning(field(pid, "search_msg"))
                if results:
                    by_bc = {r["barcode"]: r for r in results}
                    st.selectbox("Pick the right product", list(by_bc), index=None, key=f"picked_{pid}",
                                 placeholder="Choose one",
                                 format_func=lambda bc: (by_bc[bc]["display"] or bc)
                                 + ("" if by_bc[bc]["has_ingredients"] else " (no ingredients listed)"))
            elif method == "Paste ingredients":
                st.text_area("Ingredient list (copy it from the pack or website)", key=f"pasted_{pid}", height=120)
            else:
                st.caption("Tip: crop the photo to just the ingredient list for the most complete reading.")
                st.file_uploader("Photo of the ingredient label (JPEG or PNG, under 10 MB). Reading starts as soon "
                                 "as you add it.", type=["jpg", "jpeg", "png"], key=f"photo_{pid}",
                                 on_change=queue, args=("extract", pid))
                if ss.pop(f"todo_extract_{pid}", False):
                    start_photo_read(pid)
                photo_status(pid, t["category"])
                show_msg(field(pid, "extract_msg"))
                if field(pid, "extracted") is not None:
                    st.text_area("Ingredients read from the photo (you can edit this)", key=f"extracted_{pid}",
                                 height=120)
            if len(ss.products) > MIN_PRODUCTS:
                st.button("Remove this product", key=f"remove_{pid}", on_click=remove_product, args=(pid,))
    if len(ss.products) < MAX_PRODUCTS:
        st.button("Add another product", on_click=add_product, key="add_product")

    step(5, "Compare")
    filled = [read_product(p) for p in ss.products]
    missing = problems(ptype, concerns, filled)
    if missing:
        st.caption("Before you can compare: " + " ".join(missing))
    if st.button("Compare", type="primary", disabled=bool(missing), key="compare"):
        try:
            with st.spinner("Comparing..."):
                ss.result = api.compare(build_request(ptype, concerns, profile, filled))
            ss.compare_error = None
        except api_client.ApiProblem as e:
            ss.result, ss.compare_error = None, e.message


# ---------------- results ----------------

if ss.get("compare_error"):
    st.error(ss.compare_error)

result = ss.get("result")
if result:
    st.markdown("<h2>Results</h2>", unsafe_allow_html=True)
    if result["ranking"]:
        rows = []
        for r in result["ranking"]:
            tied = ' <span class="tag">tied</span>' if r["tied"] else ""
            tied += "".join(f' <span class="tag pore">✓ {esc(t)}</span>' for t in r.get("tags", []))
            first = " first" if r["rank"] == 1 else ""
            why = f'<span class="why">{esc(r["why"])}</span>' if r.get("why") else ""
            if r.get("worth_knowing"):
                why += f'<span class="why worth">{esc(r["worth_knowing"])}</span>'
            rows.append(f'<div class="rank{first}"><span class="num">{r["rank"]}</span>'
                        f'<span class="name">{esc(r["display_name"])}</span>{tied}{why}</div>')
        st.markdown("".join(rows), unsafe_allow_html=True)
        if result.get("order_note"):
            link = (f' <a href="{esc(result["order_source"], quote=True)}" target="_blank" rel="noopener">Source</a>'
                    if result.get("order_source") else "")
            st.markdown(f'<div class="order-note{" close" if result.get("close_call") else ""}">'
                        f'{esc(result["order_note"])}{link}</div>', unsafe_allow_html=True)
    else:
        st.warning("We need ingredients for at least 2 products to rank them.")

    st.markdown(f'<div class="summary">{esc(result["summary"])}</div>', unsafe_allow_html=True)

    for i, p in enumerate(result["products"]):
        with st.container(border=True, key=f"card_result_{i}"):
            st.subheader(p["display_name"])
            src = SOURCE_LABELS.get(p["ingredient_source"], p["ingredient_source"])
            st.caption(f"Ingredients from: {src}" + (f". {p['note']}" if p.get("note") else ""))
            for t in p.get("tags", []):
                st.markdown(f'<div class="flag suit"><span class="pill">✓ {esc(t)}</span>'
                            f'<span class="why">Checked against the ingredients lab studies have linked to clogged '
                            f'pores. Skin reacts differently, so patch test new products.</span></div>',
                            unsafe_allow_html=True)
            if not p["flags"]:
                st.write("We didn't spot ingredients commonly used for your concerns in this one.")
            for f in p["flags"]:
                suit = f["flag_type"] == "may_suit"
                pill = "✓ May suit" if suit else "! May not suit"
                st.markdown(
                    f'<div class="flag {"suit" if suit else "caution"}"><span class="pill">{pill}</span>'
                    f'<b>{esc(sentence_case(f.get("plain_name") or f["ingredient_family"]))}</b> '
                    f'({esc(", ".join(f["matched_ingredients"]))}): {esc(short_label(f["label"]))}.'
                    f'<span class="why">{esc(f["reason"])} '
                    f'<a href="{esc(f["source"], quote=True)}" target="_blank" rel="noopener">Source</a></span></div>',
                    unsafe_allow_html=True)
            if p.get("ingredients"):
                with st.expander("Full ingredient list"):
                    st.write(", ".join(p["ingredients"]))

    for u in result["unresolved"]:
        st.warning(f"**{u['display_name']}**: {REASON_LABELS.get(u['reason'], 'Not found')}. {u['message']}")

    st.caption(result["disclaimer"])
