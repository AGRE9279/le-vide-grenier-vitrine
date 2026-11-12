"""Le Vide-Grenier — vitrine publique.

Les habitants voient les objets vérifiés et garantis, commandent par WhatsApp,
proposent un objet à vendre ou disent ce qu'ils cherchent.
Lecture seule sur les objets publiés ; aucune donnée sensible n'est accessible.
"""
from pathlib import Path
from urllib.parse import quote

import streamlit as st
from postgrest.types import ReturnMethod
from supabase import create_client

ICONE = Path(__file__).with_name("logo_icone.png")
st.set_page_config(page_title="Le Vide-Grenier — Bonnes affaires vérifiées et garanties",
                   page_icon=str(ICONE) if ICONE.exists() else "🏠", layout="centered")

URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]
NUMERO_WHATSAPP = "2250595955803"
NUMERO_AFFICHE = "05 95 95 58 03"

BLEU, ORANGE = "#14365A", "#F08A24"
CATEGORIES = {
    "tout": "Tout",
    "electronique": "Électronique",
    "maison": "Maison et cuisine",
    "habits": "Habits et chaussures",
    "ecole_enfants": "École et enfants",
    "autre": "Autre",
}
ETATS = {"neuf": "Neuf", "bon": "Bon état", "use": "Usé"}


@st.cache_resource
def client():
    return create_client(URL, KEY)


@st.cache_data(ttl=60, show_spinner=False)
def objets_en_vente():
    return client().table("objets").select(
        "id, code_vg, titre, description, categorie, etat, defauts, prix_vente, est_appareil, photos, statut, created_at, ville_id"
    ).in_("statut", ["publie", "reserve"]).order("created_at", desc=True).execute().data


@st.cache_data(ttl=300, show_spinner=False)
def liste_villes():
    return client().table("villes").select("id, nom").order("nom").execute().data


def fcfa(n):
    return f"{int(n or 0):,} FCFA".replace(",", " ")


def lien_commande(code):
    return f"https://wa.me/{NUMERO_WHATSAPP}?text={quote('Bonjour, je veux ' + code)}"


def lien_whatsapp(texte):
    return f"https://wa.me/{NUMERO_WHATSAPP}?text={quote(texte)}"


MARQUE = (
    '<svg width="{t}" height="{t}" viewBox="0 0 140 126" role="img" aria-label="Logo Le Vide-Grenier">'
    f'<path d="M8 58 L70 10 L132 58" fill="none" stroke="{ORANGE}" stroke-width="12" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
    f'<rect x="24" y="52" width="92" height="66" rx="10" fill="{BLEU}"/>'
    '<text x="70" y="102" text-anchor="middle" font-family="\'Baloo 2\', sans-serif" font-weight="800" '
    'font-size="46" fill="#FFFFFF">VG</text></svg>'
)

st.markdown(
    "<style>@import url('https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;800&display=swap');"
    ".block-container{padding-top:3.2rem;max-width:860px}"
    ".vg-garantie{background:#EEF3F9;border-radius:12px;padding:10px 14px;font-size:15px;margin:6px 0 14px}"
    ".vg-prix{font-family:'Baloo 2',sans-serif;font-weight:800;font-size:24px;color:#14365A;line-height:1.1}"
    ".vg-code{font-size:12px;color:#5A6472;letter-spacing:1px}"
    ".vg-badge{display:inline-block;background:#FDE7D1;color:#8A3F00;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:600}"
    "</style>",
    unsafe_allow_html=True,
)

# ---------- En-tête ----------
st.markdown(
    '<div style="display:flex;align-items:center;gap:14px">'
    + MARQUE.format(t=64)
    + '<div style="line-height:1">'
    f'<div style="font-family:\'Baloo 2\',sans-serif;font-weight:800;font-size:34px;color:{BLEU}">Le Vide-Grenier</div>'
    '<div style="font-weight:600;font-size:11px;letter-spacing:2px;color:#9A4A06;margin-top:4px">'
    'LES BONNES AFFAIRES DE LA MAISON</div></div></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="vg-garantie">🛡️ <b>Chaque objet est vérifié, testé et garanti</b> : '
    "48 h, et 7 jours pour les appareils. Pas conforme = remboursé.</div>",
    unsafe_allow_html=True,
)

onglet_acheter, onglet_vendre, onglet_cherche, onglet_infos = st.tabs(
    ["🛒 Acheter", "💰 Vendre un objet", "🔎 Je cherche…", "ℹ️ Comment ça marche"]
)

# ---------- Acheter ----------
with onglet_acheter:
    try:
        objets = objets_en_vente()
    except Exception:
        objets = None
        st.error("La vitrine est momentanément indisponible. Réessayez dans un instant, "
                 f"ou écrivez-nous sur WhatsApp au {NUMERO_AFFICHE}.")
    if objets is not None:
        try:
            villes = liste_villes()
        except Exception:
            villes = []
        noms_villes = {v["id"]: v["nom"] for v in villes}
        ville_choisie = st.selectbox("📍 Ville", [None] + [v["id"] for v in villes],
                                     format_func=lambda i: "Toutes les villes" if i is None else noms_villes[i]) \
            if len(villes) > 1 else None
        recherche = st.text_input("Rechercher", placeholder="Ex. : télé, frigo, uniforme…",
                                  label_visibility="collapsed")
        cat = st.selectbox("Catégorie", list(CATEGORIES), format_func=CATEGORIES.get)
        tri = st.radio("Trier", ["Plus récents", "Prix croissant", "Prix décroissant"],
                       horizontal=True, label_visibility="collapsed")

        mot = recherche.strip().lower()
        liste = [
            o for o in objets
            if (cat == "tout" or o["categorie"] == cat)
            and (ville_choisie is None or o.get("ville_id") == ville_choisie)
            and (not mot or mot in f"{o['titre']} {o.get('description') or ''} {o['code_vg']}".lower())
        ]
        if tri == "Prix croissant":
            liste.sort(key=lambda o: o["prix_vente"] or 0)
        elif tri == "Prix décroissant":
            liste.sort(key=lambda o: -(o["prix_vente"] or 0))

        st.caption(f"{len(liste)} objet(s) disponible(s)")
        if not liste:
            st.info("Aucun objet ne correspond pour le moment. Dites-nous ce que vous cherchez "
                    "dans l'onglet « 🔎 Je cherche… » : on vous prévient dès qu'il arrive.")

        for i in range(0, len(liste), 2):
            colonnes = st.columns(2)
            for col, o in zip(colonnes, liste[i:i + 2]):
                with col, st.container(border=True):
                    if o.get("photos"):
                        st.image(o["photos"][0], width="stretch")
                    reserve = o["statut"] == "reserve"
                    st.markdown(f'<div class="vg-code">{o["code_vg"]}'
                                + (' &nbsp;<span class="vg-badge">Réservé</span>' if reserve else "")
                                + "</div>", unsafe_allow_html=True)
                    st.markdown(f"**{o['titre']}**")
                    st.markdown(f'<div class="vg-prix">{fcfa(o["prix_vente"])}</div>', unsafe_allow_html=True)
                    etat = ETATS.get(o["etat"], o["etat"])
                    if o.get("defauts") and o["defauts"].strip().lower() not in ("neant", "néant", "aucun", "rien"):
                        etat += f" — {o['defauts']}"
                    lieu = f" · 📍 {noms_villes[o['ville_id']]}" if len(villes) > 1 and o.get("ville_id") in noms_villes else ""
                    st.caption(f"{etat} · garanti {'7 jours' if o['est_appareil'] else '48 h'}{lieu}")
                    if o.get("description"):
                        with st.expander("Détails"):
                            st.write(o["description"])
                            if len(o.get("photos") or []) > 1:
                                st.image(o["photos"][1:], width=120)
                    if reserve:
                        st.button("Déjà réservé", disabled=True, key=f"r{o['id']}", width="stretch")
                    else:
                        st.link_button("📲 Commander sur WhatsApp", lien_commande(o["code_vg"]),
                                       type="primary", width="stretch")

# ---------- Vendre ----------
with onglet_vendre:
    st.markdown("**Vous avez un objet à vendre ?** Nous le vérifions, le photographions, le vendons "
                "et vous payons après la garantie. Rien à faire de votre côté.")
    st.caption("Commission : 15 % en dépôt-vente (minimum 500 FCFA) · 20 % pour les gros objets vérifiés chez vous.")
    with st.form("vendre", clear_on_submit=True):
        nom = st.text_input("Votre nom")
        tel = st.text_input("Votre numéro WhatsApp", placeholder="07 00 00 00 00")
        try:
            _villes = liste_villes()
        except Exception:
            _villes = []
        ville_v = st.selectbox("Votre ville", _villes, format_func=lambda v: v["nom"]) if _villes else None
        quartier = st.text_input("Votre quartier")
        categorie = st.selectbox("Catégorie", [c for c in CATEGORIES if c != "tout"], format_func=CATEGORIES.get)
        objet = st.text_area("L'objet (marque, état, depuis quand…)", max_chars=500)
        prix = st.number_input("Prix souhaité (FCFA)", min_value=0, step=500)
        envoye = st.form_submit_button("Envoyer ma proposition", type="primary")
    if envoye:
        tel_ok = "".join(ch for ch in tel if ch.isdigit() or ch in " +")
        if len(nom.strip()) < 2 or len(tel_ok.replace(" ", "")) < 8 or len(objet.strip()) < 3:
            st.error("Indiquez votre nom, un numéro WhatsApp valide et une description de l'objet.")
        else:
            try:
                client().table("propositions").insert({
                    "type": "vendre", "nom": nom.strip(), "telephone": tel_ok.strip(),
                    "ville_id": ville_v["id"] if ville_v else None,
                    "quartier": quartier.strip() or None, "categorie": categorie,
                    "texte": objet.strip(), "prix": int(prix) or None,
                }, returning=ReturnMethod.minimal).execute()  # le public envoie sans relire
                st.success("Merci ! Votre proposition est bien reçue. Nous vous contactons sur WhatsApp.")
                st.link_button("📸 Envoyer maintenant une photo de l'objet sur WhatsApp",
                               lien_whatsapp(f"Bonjour, je viens de proposer un objet à vendre ({objet.strip()[:60]}). Voici la photo :"))
            except Exception:
                st.error(f"L'envoi n'a pas marché. Écrivez-nous directement sur WhatsApp au {NUMERO_AFFICHE}.")

# ---------- Je cherche ----------
with onglet_cherche:
    st.markdown("**Vous ne trouvez pas ce qu'il vous faut ?** Dites-le-nous : dès qu'un objet correspondant "
                "arrive, nous vous prévenons sur WhatsApp.")
    with st.form("cherche", clear_on_submit=True):
        nom2 = st.text_input("Votre nom", key="nom2")
        tel2 = st.text_input("Votre numéro WhatsApp", placeholder="07 00 00 00 00", key="tel2")
        try:
            _villes2 = liste_villes()
        except Exception:
            _villes2 = []
        ville_c = st.selectbox("Votre ville", _villes2, format_func=lambda v: v["nom"], key="ville2") if _villes2 else None
        categorie2 = st.selectbox("Catégorie", [c for c in CATEGORIES if c != "tout"],
                                  format_func=CATEGORIES.get, key="cat2")
        cherche = st.text_area("Ce que vous cherchez", placeholder="Ex. : un frigo qui marche bien", max_chars=500)
        budget = st.number_input("Votre budget maximum (FCFA)", min_value=0, step=500)
        envoye2 = st.form_submit_button("Envoyer ma recherche", type="primary")
    if envoye2:
        tel_ok2 = "".join(ch for ch in tel2 if ch.isdigit() or ch in " +")
        if len(nom2.strip()) < 2 or len(tel_ok2.replace(" ", "")) < 8 or len(cherche.strip()) < 3:
            st.error("Indiquez votre nom, un numéro WhatsApp valide et ce que vous cherchez.")
        else:
            try:
                client().table("propositions").insert({
                    "type": "cherche", "nom": nom2.strip(), "telephone": tel_ok2.strip(),
                    "ville_id": ville_c["id"] if ville_c else None,
                    "categorie": categorie2, "texte": cherche.strip(), "prix": int(budget) or None,
                }, returning=ReturnMethod.minimal).execute()  # le public envoie sans relire
                st.success("C'est noté ! Nous vous prévenons sur WhatsApp dès que nous trouvons.")
            except Exception:
                st.error(f"L'envoi n'a pas marché. Écrivez-nous directement sur WhatsApp au {NUMERO_AFFICHE}.")

# ---------- Comment ça marche ----------
with onglet_infos:
    st.markdown(
        "#### Pour acheter\n"
        "1. Choisissez un objet et touchez **« Commander sur WhatsApp »**.\n"
        "2. Payez **Le Vide-Grenier** par Mobile Money ou en espèces à la livraison — jamais le vendeur directement.\n"
        "3. Nous livrons (300 à 500 FCFA dans la ville) ou vous venez le chercher.\n"
        "4. **Garantie** : 48 h (7 jours pour les appareils). Objet non conforme ou en panne = repris et remboursé.\n\n"
        "#### Pour vendre\n"
        "1. Proposez votre objet dans l'onglet **« Vendre un objet »** ou sur WhatsApp.\n"
        "2. Nous le vérifions (pièce d'identité, et facture pour les téléphones), le photographions et le publions.\n"
        "3. Une fois vendu et la garantie passée, vous êtes payé par Mobile Money, moins notre commission.\n\n"
        "#### Pourquoi nous faire confiance ?\n"
        "Chaque objet porte une étiquette **VG** : il a été contrôlé par notre équipe, et l'argent de l'acheteur "
        "reste chez nous jusqu'à la fin de la garantie."
    )
    st.link_button(f"💬 Nous écrire sur WhatsApp ({NUMERO_AFFICHE})",
                   lien_whatsapp("Bonjour Le Vide-Grenier, j'ai une question :"))

st.divider()
st.caption(f"Le Vide-Grenier · Vérifié · Garanti · WhatsApp {NUMERO_AFFICHE}")
