import io
import os
import math
import datetime as dt

import pandas as pd
import streamlit as st

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# PNG (tablolu görsel çıktı)
import matplotlib.pyplot as plt


# -----------------------------
# Helpers
# -----------------------------
def today_tr():
    # Streamlit Cloud genelde UTC çalışır; tarih alanında sapma olmasın diye sadece "bugün" mantığı yeterli.
    # İsterseniz timezone-aware kütüphane eklenebilir.
    return dt.date.today()

def eur_fmt(x: float) -> str:
    """1.329 gibi TR/AB formatında EUR göster."""
    if x is None or (isinstance(x, float) and (math.isnan(x))):
        return ""
    s = f"{x:,.0f}"  # 1,329
    s = s.replace(",", "_").replace(".", ",").replace("_", ".")  # 1.329
    return s

def eur_fmt_dec(x: float, decimals: int = 2) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x))):
        return ""
    s = f"{x:,.{decimals}f}"  # 1,329.50
    s = s.replace(",", "_").replace(".", ",").replace("_", ".")  # 1.329,50
    return s

def normalize_price_list(df: pd.DataFrame) -> pd.DataFrame:
    """
    Beklenen kolonlar:
      MODEL | AÇIKLAMA | LİSTE FİYATI
    Excel'den farklı adlar gelirse buradan maplenir.
    """
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # olası kolon isimleri
    col_map = {}
    for c in df.columns:
        uc = c.upper()
        if uc in ["MODEL", "KOD", "ÜRÜN KODU", "URUN KODU", "STOK KODU"]:
            col_map[c] = "MODEL"
        elif uc in ["AÇIKLAMA", "ACIKLAMA", "ÜRÜN AÇIKLAMASI", "URUN ACIKLAMASI", "DESCRIPTION"]:
            col_map[c] = "AÇIKLAMA"
        elif uc in ["LİSTE FİYATI", "LISTE FIYATI", "FİYAT", "FIYAT", "PRICE", "LİSTE FİYAT"]:
            col_map[c] = "LİSTE FİYATI"

    df = df.rename(columns=col_map)

    required = ["MODEL", "AÇIKLAMA", "LİSTE FİYATI"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Fiyat listesinde kolon eksik: {missing}. Beklenen: {required}")

    df = df[required].dropna(subset=["MODEL"]).copy()
    df["MODEL"] = df["MODEL"].astype(str).str.strip()
    df["AÇIKLAMA"] = df["AÇIKLAMA"].astype(str).str.strip()

    # fiyatı sayıya çevir
    def to_num(v):
        if pd.isna(v):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        # 1.234,56 veya 1234,56 veya 1234.56 yakala
        s = s.replace(" ", "")
        if "," in s and "." in s:
            # TR format varsayalım: 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:
            # tek ayraç varsa virgülü noktaya çevir
            s = s.replace(",", ".")
        try:
            return float(s)
        except:
            return None

    df["LİSTE FİYATI"] = df["LİSTE FİYATI"].apply(to_num)
    df = df.dropna(subset=["LİSTE FİYATI"])
    df["LİSTE FİYATI"] = df["LİSTE FİYATI"].astype(float)

    return df

def calc_discounted(list_price: float, discount_pct: float) -> float:
    return list_price * (1.0 - (discount_pct / 100.0))

def build_pdf_bytes(meta: dict, cart_df: pd.DataFrame, total: float) -> bytes:
    """
    meta: teklif üst bilgileri
    cart_df kolonları: MODEL, AÇIKLAMA, ADET, BİRİM (EUR), TOPLAM (EUR)
    """
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title="Teklif"
    )

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    h = styles["Heading2"]

    story = []
    story.append(Paragraph("TEKLİF", h))
    story.append(Spacer(1, 6 * mm))

    # Üst Bilgiler (2 kolonlu tablo)
    info_data = [
        ["Tarih", meta["tarih"]],
        ["Geçerlilik", meta["gecerlilik"]],
        ["Firma İsmi", meta["firma"]],
        ["Yetkili İsmi", meta["yetkili"]],
        ["Proje İsmi", meta["proje"]],
        ["İskonto Oranı", f"%{meta['iskonto']}"],
        ["Teklifi Hazırlayan", meta["hazirlayan"]],
        ["E-mail", meta["email"]],
        ["Telefon", meta["telefon"]],
    ]
    info_tbl = Table(info_data, colWidths=[35 * mm, 135 * mm])
    info_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (1, 1), colors.whitesmoke),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 8 * mm))

    # Ürün Tablosu
    table_header = ["Model", "Açıklama", "Adet", "Birim (EUR)", "Tutar (EUR)"]
    rows = [table_header]

    for _, r in cart_df.iterrows():
        rows.append([
            str(r["MODEL"]),
            str(r["AÇIKLAMA"]),
            str(int(r["ADET"])),
            eur_fmt_dec(float(r["BİRİM (EUR)"]), 2),
            eur_fmt_dec(float(r["TOPLAM (EUR)"]), 2),
        ])

    prod_tbl = Table(rows, colWidths=[40 * mm, 78 * mm, 14 * mm, 28 * mm, 28 * mm])
    prod_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, 1), (2, -1), "CENTER"),
        ("ALIGN", (3, 1), (4, -1), "RIGHT"),
    ]))

    story.append(prod_tbl)
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph(f"<b>Toplam:</b> {eur_fmt_dec(total, 2)} EUR + KDV", normal))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("Not: Fiyatlar EUR bazında olup KDV hariçtir.", normal))

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf

def build_table_png_bytes(cart_df: pd.DataFrame, meta: dict, total: float) -> bytes:
    """
    Ekran görüntüsü mantığı için: tabloyu PNG'e basıp indirilebilir yapıyoruz.
    """
    # Görsel için daha kompakt dataframe
    view = cart_df.copy()
    view["BİRİM (EUR)"] = view["BİRİM (EUR)"].map(lambda v: eur_fmt_dec(float(v), 2))
    view["TOPLAM (EUR)"] = view["TOPLAM (EUR)"].map(lambda v: eur_fmt_dec(float(v), 2))
    view["ADET"] = view["ADET"].astype(int).astype(str)

    title = f"{meta['firma']} | {meta['proje']} | % {meta['iskonto']} iskonto | Toplam: {eur_fmt_dec(total, 2)} EUR + KDV"

    fig_h = 1.2 + 0.35 * max(1, len(view))
    fig, ax = plt.subplots(figsize=(12, fig_h))
    ax.axis("off")
    ax.set_title(title, fontsize=11, pad=10)

    tbl = ax.table(
        cellText=view[["MODEL", "AÇIKLAMA", "ADET", "BİRİM (EUR)", "TOPLAM (EUR)"]].values,
        colLabels=["MODEL", "AÇIKLAMA", "ADET", "BİRİM (EUR)", "TOPLAM (EUR)"],
        cellLoc="left",
        colLoc="left",
        loc="center",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1, 1.2)

    buf = io.BytesIO()
    plt.tight_layout()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# -----------------------------
# Streamlit App
# -----------------------------
st.set_page_config(page_title="Teklif Oluşturucu", layout="wide")

st.title("Teklif Oluşturucu (Web)")

# Session state
if "cart" not in st.session_state:
    st.session_state.cart = []  # list of dict rows

if "price_list" not in st.session_state:
    st.session_state.price_list = None

# Sidebar - Teklif üst bilgileri
with st.sidebar:
    st.header("Teklif Bilgileri")

    tarih = today_tr()
    gecerlilik = tarih + dt.timedelta(days=7)

    firma = st.text_input("FİRMA İSMİ", value="")
    yetkili = st.text_input("YETKİLİ İSMİ", value="")
    proje = st.text_input("PROJE İSMİ", value="")
    iskonto = st.number_input("İSKONTO ORANI (%)", min_value=0.0, max_value=100.0, value=40.0, step=0.5)
    hazirlayan = st.text_input("TEKLİFİ HAZIRLAYAN", value="")
    email = st.text_input("EMAİL", value="")
    telefon = st.text_input("TELEFON", value="")

    st.divider()
    st.caption(f"Tarih: {tarih.strftime('%d.%m.%Y')}")
    st.caption(f"Geçerlilik: {gecerlilik.strftime('%d.%m.%Y')} (7 gün)")

    st.divider()
    st.subheader("Fiyat Listesi")

    up = st.file_uploader("Excel/CSV yükle (MODEL, AÇIKLAMA, LİSTE FİYATI)", type=["xlsx", "xls", "csv"])
    if up is not None:
        try:
            if up.name.lower().endswith(".csv"):
                df_pl = pd.read_csv(up)
            else:
                df_pl = pd.read_excel(up)
            df_pl = normalize_price_list(df_pl)
            st.session_state.price_list = df_pl
            st.success(f"Yüklendi: {len(df_pl)} ürün")
        except Exception as e:
            st.session_state.price_list = None
            st.error(f"Fiyat listesi okunamadı: {e}")

    # Local fallback
    if st.session_state.price_list is None:
        if os.path.exists("price_list.csv"):
            try:
                df_pl = pd.read_csv("price_list.csv")
                df_pl = normalize_price_list(df_pl)
                st.session_state.price_list = df_pl
                st.info("price_list.csv kullanılıyor.")
            except Exception as e:
                st.warning(f"price_list.csv okunamadı: {e}")

    # Built-in minimal fallback for demo
    if st.session_state.price_list is None:
        demo = pd.DataFrame([
            {"MODEL": "KSH-0800-V5.1", "AÇIKLAMA": "SOLAR & ISI POMPASI BOYLER - ÇİFT SERPANTİNLİ 800 LİTRE - 10 BAR", "LİSTE FİYATI": 2215},
            {"MODEL": "KSH-1000-V5.1", "AÇIKLAMA": "SOLAR & ISI POMPASI BOYLER - ÇİFT SERPANTİNLİ 1000 LİTRE - 10 BAR", "LİSTE FİYATI": 2468},
            {"MODEL": "KBS-B-0800-V5.1", "AÇIKLAMA": "TEK SERPANTİNLİ BOYLER 800 LİTRE - BASIC 10 BAR", "LİSTE FİYATI": 1494},
            {"MODEL": "KBS-B-1000-V5.1", "AÇIKLAMA": "TEK SERPANTİNLİ BOYLER 1000 LİTRE - BASIC 10 BAR", "LİSTE FİYATI": 1612},
        ])
        st.session_state.price_list = demo
        st.warning("Demo fiyat listesi aktif. Kendi listenizi yükleyin veya repo'ya price_list.csv ekleyin.")

    st.divider()
    if st.button("Sepeti sıfırla", use_container_width=True):
        st.session_state.cart = []
        st.rerun()


# Main layout
pl = st.session_state.price_list.copy()

colA, colB = st.columns([1.1, 1.2], gap="large")

with colA:
    st.subheader("Ürün Ekle")

    q = st.text_input("Ürün arama (ör: KSH)", value="")
    filtered = pl
    if q.strip():
        qs = q.strip().upper()
        filtered = pl[
            pl["MODEL"].str.upper().str.contains(qs, na=False) |
            pl["AÇIKLAMA"].str.upper().str.contains(qs, na=False)
        ].copy()

    # seçim listesi: "MODEL | AÇIKLAMA (fiyat)"
    filtered["LABEL"] = filtered.apply(lambda r: f"{r['MODEL']} | {r['AÇIKLAMA']} | {eur_fmt(r['LİSTE FİYATI'])} EUR", axis=1)

    if len(filtered) == 0:
        st.info("Arama kriterine uygun ürün yok.")
        selected = None
    else:
        selected_label = st.selectbox("Ürün seç", filtered["LABEL"].tolist())
        selected = filtered[filtered["LABEL"] == selected_label].iloc[0].to_dict()

    qty = st.number_input("Adet", min_value=1, value=1, step=1)

    if selected:
        list_price = float(selected["LİSTE FİYATI"])
        unit = calc_discounted(list_price, float(iskonto))

        st.markdown("**Seçilen ürün özeti**")
        st.write(f"**Model:** {selected['MODEL']}")
        st.write(f"**Açıklama:** {selected['AÇIKLAMA']}")
        st.write(f"**Liste fiyatı:** {eur_fmt_dec(list_price, 2)} EUR")
        st.write(f"**İskontolu birim fiyat:** {eur_fmt_dec(unit, 2)} EUR + KDV")

        if st.button("Sepete ekle", type="primary", use_container_width=True):
            # Aynı model varsa adet arttır
            found = False
            for r in st.session_state.cart:
                if r["MODEL"] == selected["MODEL"]:
                    r["ADET"] = int(r["ADET"]) + int(qty)
                    found = True
                    break
            if not found:
                st.session_state.cart.append({
                    "MODEL": selected["MODEL"],
                    "AÇIKLAMA": selected["AÇIKLAMA"],
                    "LİSTE FİYATI": list_price,
                    "ADET": int(qty),
                })
            st.rerun()


with colB:
    st.subheader("Sepet / Teklif Kalemleri")

    if len(st.session_state.cart) == 0:
        st.info("Sepet boş. Soldan ürün ekleyin.")
    else:
        cart_df = pd.DataFrame(st.session_state.cart)

        # hesaplar
        cart_df["BİRİM (EUR)"] = cart_df["LİSTE FİYATI"].apply(lambda p: calc_discounted(float(p), float(iskonto)))
        cart_df["TOPLAM (EUR)"] = cart_df["BİRİM (EUR)"] * cart_df["ADET"].astype(int)

        total = float(cart_df["TOPLAM (EUR)"].sum())

        # editör: adet değiştir / sil
        edit_df = cart_df[["MODEL", "AÇIKLAMA", "ADET", "BİRİM (EUR)", "TOPLAM (EUR)"]].copy()
        edit_df["SİL"] = False

        edited = st.data_editor(
            edit_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ADET": st.column_config.NumberColumn("ADET", min_value=1, step=1),
                "BİRİM (EUR)": st.column_config.NumberColumn("BİRİM (EUR)", format="%.2f"),
                "TOPLAM (EUR)": st.column_config.NumberColumn("TOPLAM (EUR)", format="%.2f"),
                "SİL": st.column_config.CheckboxColumn("SİL"),
            },
            disabled=["MODEL", "AÇIKLAMA", "BİRİM (EUR)", "TOPLAM (EUR)"],
            key="cart_editor",
        )

        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("Değişiklikleri uygula", use_container_width=True):
                # adet güncelle + sil
                keep = []
                for _, r in edited.iterrows():
                    if bool(r.get("SİL", False)):
                        continue
                    keep.append({
                        "MODEL": r["MODEL"],
                        "AÇIKLAMA": r["AÇIKLAMA"],
                        "LİSTE FİYATI": float(cart_df[cart_df["MODEL"] == r["MODEL"]]["LİSTE FİYATI"].iloc[0]),
                        "ADET": int(r["ADET"]),
                    })
                st.session_state.cart = keep
                st.rerun()

        with c2:
            st.metric("Kümülatif Toplam", f"{eur_fmt_dec(total, 2)} EUR + KDV")

        st.divider()

        # Tek satır çıktı (senin örneğin gibi)
        st.markdown("**Satır formatı (müşteriye kopyala-yapıştır)**")
        lines = []
        for _, r in cart_df.iterrows():
            unit_txt = eur_fmt_dec(float(r["BİRİM (EUR)"]), 2)
            lines.append(f"{r['MODEL']} / {r['AÇIKLAMA']} / {int(r['ADET'])} ADET / {unit_txt} EUR + KDV")
        st.code("\n".join(lines), language="text")

        meta = {
            "tarih": tarih.strftime("%d.%m.%Y"),
            "gecerlilik": gecerlilik.strftime("%d.%m.%Y"),
            "firma": firma.strip() or "-",
            "yetkili": yetkili.strip() or "-",
            "proje": proje.strip() or "-",
            "iskonto": float(iskonto),
            "hazirlayan": hazirlayan.strip() or "-",
            "email": email.strip() or "-",
            "telefon": telefon.strip() or "-",
        }

        # PDF
        pdf_bytes = build_pdf_bytes(meta, cart_df, total)
        st.download_button(
            label="PDF indir (teklif)",
            data=pdf_bytes,
            file_name=f"Teklif_{meta['firma'].replace(' ', '_')}_{meta['tarih'].replace('.', '-')}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

        # PNG
        png_bytes = build_table_png_bytes(cart_df, meta, total)
        st.download_button(
            label="PNG indir (ekran görüntüsü gibi)",
            data=png_bytes,
            file_name=f"Teklif_{meta['firma'].replace(' ', '_')}_{meta['tarih'].replace('.', '-')}.png",
            mime="image/png",
            use_container_width=True,
        )

st.caption("Fiyatlar EUR bazında; KDV hariç gösterilir. İskonto, liste fiyatına yüzde olarak uygulanır.")
