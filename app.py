"""Le Black — tableau de bord de l'équipe (garant, admins, vérificateurs, livreurs).

Chaque vente suit le circuit garanti :
proposé -> vérifié -> publié -> réservé -> vendu (livré, sous garantie) -> vendeur payé
"""
import io
import uuid
from urllib.parse import quote
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st
from PIL import Image, ImageOps
from supabase import create_client

BUCKET_PHOTOS = "photos-objets"
NUMERO_WHATSAPP = "2250595955803"        # numéro WhatsApp Business du Vide-Grenier (format international)
NUMERO_AFFICHE = "05 95 95 58 03"
MAX_PHOTOS = 4

from pathlib import Path

ICONE = Path(__file__).with_name("logo_icone.png")
st.set_page_config(page_title="Le Black — Équipe",
                   page_icon=str(ICONE) if ICONE.exists() else "🏷️", layout="wide")

BLEU, ORANGE = "#14365A", "#F08A24"
MARQUE_SVG = (
    '<svg width="{t}" height="{t}" viewBox="0 0 140 126" role="img" aria-label="Logo Le Black">'
    f'<path d="M8 58 L70 10 L132 58" fill="none" stroke="{ORANGE}" stroke-width="12" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
    f'<rect x="24" y="52" width="92" height="66" rx="10" fill="{BLEU}"/>'
    '<text x="70" y="102" text-anchor="middle" font-family="\'Baloo 2\', sans-serif" font-weight="800" '
    'font-size="46" fill="#FFFFFF">LB</text></svg>'
)


def logo(grand=True):
    """Logo piste B : le toit du grenier au-dessus de VG."""
    t, nom, sous = (84, 46, 12) if grand else (48, 26, 9)
    st.markdown(
        "<style>@import url('https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;800&display=swap');</style>"
        f'<div style="display:flex;align-items:center;gap:{t // 5}px;margin-bottom:8px">'
        + MARQUE_SVG.format(t=t) +
        '<div style="display:flex;flex-direction:column;line-height:1">'
        f'<span style="font-family:\'Baloo 2\',sans-serif;font-weight:800;font-size:{nom}px;color:{BLEU}">Le Black</span>'
        f'<span style="font-weight:600;font-size:{sous}px;letter-spacing:2px;text-transform:uppercase;color:#9A4A06;margin-top:4px">'
        'Les bonnes affaires d’occasion</span></div></div>',
        unsafe_allow_html=True,
    )


URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]

CATEGORIES = {
    "habits": "Habits et chaussures",
    "maison": "Maison et cuisine",
    "electronique": "Électronique",
    "ecole_enfants": "École et enfants",
    "autre": "Autre",
}
ETATS = {"neuf": "Neuf", "bon": "Bon état", "use": "Usé"}
FORMULES = {"depot": "Dépôt-vente (15 %, min. 500 FCFA)", "domicile": "Vente vérifiée à domicile (20 %, min. 1 000 FCFA)",
            "partenaire": "Vendeur partenaire (taux du partenaire)"}
STATUTS_OBJET = {
    "propose": "Proposé", "refuse": "Refusé", "verifie": "Vérifié", "publie": "Publié",
    "reserve": "Réservé", "vendu": "Vendu (sous garantie)", "vendeur_paye": "Vendeur payé", "rendu": "Rendu au vendeur",
}
ROLES = {"garant": "Garant", "admin": "Admin", "verificateur": "Vérificateur", "livreur": "Livreur",
         "commercial": "Vendeur partenaire"}


# ---------- Outils ----------

def sb():
    """Un client Supabase par session : chaque membre de l'équipe a sa propre connexion."""
    if "sb" not in st.session_state:
        st.session_state.sb = create_client(URL, KEY)
    return st.session_state.sb


def fcfa(n):
    return f"{int(n or 0):,} FCFA".replace(",", " ")


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def jolie_date(s):
    d = parse_dt(s)
    return d.strftime("%d/%m/%Y %H:%M") if d else "—"


def maintenant():
    return datetime.now(timezone.utc).isoformat()


def commission(formule, prix, taux_partenaire=None):
    if taux_partenaire is not None:
        return round(prix * float(taux_partenaire))
    taux, minimum = (0.20, 1000) if formule == "domicile" else (0.15, 500)
    return max(round(prix * taux), minimum)


def pct(x):
    return f"{float(x) * 100:.0f} %"


def villes():
    return sb().table("villes").select("id, nom").eq("actif", True).order("nom").execute().data


def garantie_txt(est_appareil):
    return "7 jours" if est_appareil else "48 h"


def membre():
    return st.session_state.get("membre")


def est_garant():
    return membre() and membre()["role"] in ("garant", "admin")


def est_partenaire():
    return membre() and membre()["role"] == "commercial"


def ok(message):
    st.session_state.flash = message
    st.rerun()


def choisir_ou_creer_personne(prefixe, titre):
    """Sélectionne une personne existante ou en crée une nouvelle. Renvoie son id (ou None)."""
    personnes = sb().table("personnes").select("id, nom, telephone, quartier").order("nom").execute().data
    options = ["➕ Nouvelle personne"] + [f"{p['nom']} — {p['telephone']}" for p in personnes]
    choix = st.selectbox(titre, options, key=f"{prefixe}_choix")
    if choix != options[0]:
        return personnes[options.index(choix) - 1]["id"], None
    c1, c2, c3 = st.columns(3)
    nouvelle = {
        "nom": c1.text_input("Nom complet", key=f"{prefixe}_nom"),
        "telephone": c2.text_input("Téléphone (WhatsApp)", key=f"{prefixe}_tel"),
        "quartier": c3.text_input("Quartier", key=f"{prefixe}_quartier"),
        "piece_identite_vue": st.checkbox("Pièce d'identité vue", key=f"{prefixe}_piece"),
    }
    return None, nouvelle


def enregistrer_personne(pid, nouvelle):
    if pid:
        return pid
    if not nouvelle["nom"].strip() or not nouvelle["telephone"].strip():
        st.error("Le nom et le téléphone sont obligatoires.")
        st.stop()
    return sb().table("personnes").insert(nouvelle).execute().data[0]["id"]


def compresser_photo(fichier):
    """Redresse, réduit à 1280 px et compresse en JPEG : économise les données mobiles."""
    img = ImageOps.exif_transpose(Image.open(fichier)).convert("RGB")
    img.thumbnail((1280, 1280))
    tampon = io.BytesIO()
    img.save(tampon, format="JPEG", quality=80, optimize=True)
    return tampon.getvalue()


def envoyer_photos(objet, fichiers):
    """Envoie les photos dans Supabase Storage et les ajoute à l'objet. Renvoie la nouvelle liste."""
    photos = list(objet.get("photos") or [])
    for f in fichiers[: MAX_PHOTOS - len(photos)]:
        chemin = f"{objet['code_vg']}/{uuid.uuid4().hex[:10]}.jpg"
        sb().storage.from_(BUCKET_PHOTOS).upload(chemin, compresser_photo(f), {"content-type": "image/jpeg"})
        photos.append(sb().storage.from_(BUCKET_PHOTOS).get_public_url(chemin).rstrip("?"))
    sb().table("objets").update({"photos": photos}).eq("id", objet["id"]).execute()
    return photos


def montrer_photos(photos, largeur=160):
    if photos:
        st.image(photos, width=largeur)
    else:
        st.caption("Pas encore de photo.")


def lien_whatsapp(o):
    """Ouvre WhatsApp avec l'annonce déjà écrite : il reste à choisir le groupe et envoyer."""
    return "https://wa.me/?text=" + quote(texte_annonce(o))


def bouton_whatsapp(o, cle):
    st.link_button("📲 Envoyer dans WhatsApp", lien_whatsapp(o), type="primary")
    st.caption("WhatsApp s'ouvre avec l'annonce écrite : choisis le groupe, joins la photo si tu veux, puis Envoyer.")


def texte_annonce(o):
    lignes = [
        f"🏷️ {o['code_vg']} – {o['titre']}",
        f"💰 {fcfa(o['prix_vente'])}",
        f"✅ État : {ETATS[o['etat']]}" + (f" – {o['defauts']}" if o.get("defauts") else ""),
    ]
    if o.get("description"):
        lignes.append(f"ℹ️ {o['description']}")
    lignes += [
        f"🛡️ Vérifié par Le Black et garanti {garantie_txt(o['est_appareil'])}",
        f"📲 Pour commander, touchez ce lien : https://wa.me/{NUMERO_WHATSAPP}?text={quote('Je veux ' + o['code_vg'])}",
        f"📞 Ou écrivez « {o['code_vg']} » au {NUMERO_AFFICHE}",
    ]
    return "\n".join(lignes)


# ---------- Connexion ----------

def ecran_connexion():
    logo(grand=True)
    st.subheader("Espace équipe")
    st.caption("Réservé à l'équipe de Le Black.")
    t1, t2 = st.tabs(["Se connecter", "Première connexion : créer mon mot de passe"])
    with t1:
        with st.form("connexion"):
            email = st.text_input("E-mail")
            mdp = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter", type="primary"):
                res, erreur = None, None
                try:
                    client = create_client(URL, KEY)  # client neuf à chaque tentative
                    res = client.auth.sign_in_with_password({"email": email.strip(), "password": mdp})
                except Exception as e:
                    erreur = str(e)
                if erreur is None and res is not None and res.user is not None:
                    st.session_state.sb = client
                    st.session_state.user = res.user
                    st.rerun()
                elif erreur and "invalid login" in erreur.lower():
                    st.error("E-mail ou mot de passe incorrect.")
                elif erreur and "not confirmed" in erreur.lower():
                    st.error("E-mail pas encore confirmé : clique sur le lien reçu par e-mail.")
                else:
                    st.error(f"Connexion impossible. Détail technique : {erreur}")
    with t2:
        st.write("Utilise l'e-mail que le garant a inscrit dans l'équipe.")
        with st.form("inscription"):
            email = st.text_input("E-mail", key="ins_email")
            mdp = st.text_input("Choisis un mot de passe (8 caractères minimum)", type="password", key="ins_mdp")
            if st.form_submit_button("Créer mon mot de passe"):
                try:
                    sb().auth.sign_up({"email": email.strip(), "password": mdp})
                    st.success("C'est fait. Ouvre ta boîte mail, clique sur le lien de confirmation, puis connecte-toi.")
                except Exception as e:
                    st.error(f"Impossible de créer le compte : {e}")


def charger_membre():
    user = st.session_state.user
    rows = sb().table("equipe").select("*").eq("user_id", user.id).execute().data
    if not rows or not rows[0]["actif"]:
        st.error("Ton compte n'est pas (ou plus) dans l'équipe de Le Black. Demande au garant de t'ajouter.")
        if st.button("Se déconnecter"):
            deconnexion()
        st.stop()
    st.session_state.membre = rows[0]


def deconnexion():
    try:
        sb().auth.sign_out()
    except Exception:
        pass
    for k in ("user", "membre", "sb"):
        st.session_state.pop(k, None)
    st.rerun()


# ---------- Pages ----------

def page_tableau_de_bord():
    st.header("Tableau de bord")
    objets = sb().table("objets").select("statut, date_fin_depot, code_vg, titre").execute().data
    commandes = sb().table("commandes").select("statut, fin_garantie").execute().data
    a_payer = sb().table("vendeurs_a_payer").select("*").execute().data
    nouvelles = sb().table("propositions").select("id").eq("statut", "nouvelle").execute().data
    if nouvelles:
        st.warning(f"📨 {len(nouvelles)} nouvelle(s) proposition(s) de la vitrine à traiter (menu « Propositions »).")
    compte = lambda s: sum(1 for o in objets if o["statut"] == s)

    c = st.columns(5)
    c[0].metric("À vérifier", compte("propose"))
    c[1].metric("À publier", compte("verifie"))
    c[2].metric("En vente", compte("publie"))
    c[3].metric("Sous garantie", sum(1 for x in commandes if x["statut"] == "livree"))
    c[4].metric("Vendeurs à payer", len(a_payer), fcfa(sum(x["montant_a_verser"] for x in a_payer)))

    if a_payer:
        st.subheader("Vendeurs à payer (garantie terminée)")
        st.dataframe(pd.DataFrame(a_payer)[["code_vg", "titre", "vendeur", "telephone", "montant_vente", "commission", "montant_a_verser"]],
                     hide_index=True, width="stretch")

    bientot = [o for o in objets if o["statut"] == "publie" and o["date_fin_depot"]
               and (date.fromisoformat(o["date_fin_depot"]) - date.today()).days <= 3]
    if bientot:
        st.subheader("Dépôts qui arrivent à 30 jours")
        st.write("Propose une baisse de prix au vendeur, ou qu'il récupère l'objet sous 7 jours.")
        st.dataframe(pd.DataFrame(bientot)[["code_vg", "titre", "date_fin_depot"]], hide_index=True)


def page_nouveau_depot():
    st.header("Nouveau dépôt")
    st.caption("Étape 1 du circuit : le vendeur propose son objet.")
    n = st.session_state.setdefault("depot_n", 0)  # change à chaque dépôt : le formulaire repart vide
    liste_villes = villes()
    ville = st.selectbox("Ville", liste_villes, format_func=lambda v: v["nom"], key=f"ville{n}")
    pid, nouvelle = choisir_ou_creer_personne(f"vendeur{n}", "Vendeur")
    st.divider()
    c1, c2 = st.columns(2)
    titre = c1.text_input("Objet (ex. : Téléphone Tecno Spark 10)", key=f"titre{n}")
    categorie = c2.selectbox("Catégorie", list(CATEGORIES), format_func=CATEGORIES.get, key=f"cat{n}")
    description = st.text_area("Description (marque, taille, couleur…)", key=f"desc{n}")
    c3, c4, c5 = st.columns(3)
    etat = c3.selectbox("État annoncé", list(ETATS), format_func=ETATS.get, index=1, key=f"etat{n}")
    formule = c4.selectbox("Formule", ["depot", "domicile"], format_func=FORMULES.get, key=f"form{n}")
    prix = c5.number_input("Prix demandé par le vendeur (FCFA)", min_value=0, step=500, key=f"prix{n}")
    est_appareil = st.checkbox("Appareil électrique ou téléphone (garantie 7 jours, test obligatoire)",
                               value=categorie == "electronique", key=f"app{n}_{categorie}")
    if prix:
        st.info(f"Si l'objet est vendu {fcfa(prix)} : commission {fcfa(commission(formule, prix))}, "
                f"le vendeur reçoit {fcfa(prix - commission(formule, prix))}.")
    if st.button("Enregistrer le dépôt", type="primary"):
        if not titre.strip():
            st.error("Indique le nom de l'objet.")
            st.stop()
        if nouvelle is not None:
            nouvelle["ville_id"] = ville["id"]
        vendeur_id = enregistrer_personne(pid, nouvelle)
        o = sb().table("objets").insert({
            "vendeur_id": vendeur_id, "titre": titre.strip(), "description": description.strip() or None,
            "categorie": categorie, "etat": etat, "formule": formule, "est_appareil": est_appareil,
            "prix_demande": int(prix) or None, "ville_id": ville["id"],
            "date_depot": date.today().isoformat() if formule == "depot" else None,
        }).execute().data[0]
        st.session_state.depot_n = n + 1
        ok(f"Dépôt enregistré : écris **{o['code_vg']}** sur l'étiquette de l'objet.")


def page_verification():
    st.header("Vérification")
    st.caption("Étape 2 : tester l'objet, noter les défauts, puis le déclarer conforme ou le refuser.")
    objets = sb().table("objets").select("*, vendeur:personnes(nom, telephone, piece_identite_vue), ville:villes(nom)") \
        .eq("statut", "propose").order("created_at").execute().data
    if not objets:
        st.success("Aucun objet en attente de vérification.")
    for o in objets:
        partenaire = o.get("commercial_id") is not None
        etiquette = f" · 🤝 partenaire, {o['ville']['nom']}" if partenaire else ""
        with st.expander(f"{o['code_vg']} — {o['titre']} ({o['vendeur']['nom']}){etiquette}"):
            if partenaire:
                st.info(f"Objet d'un **vendeur partenaire** ({o['ville']['nom']}) : vérification à distance par le garant, "
                        f"sur les photos et la **vidéo de test** reçue sur WhatsApp. Commission : {pct(o['taux_commission'])}.")
                if not est_garant():
                    st.warning("Seul le garant ou un admin peut vérifier les objets des partenaires.")
                    continue
                st.link_button("💬 Demander la vidéo de test au partenaire",
                               f"https://wa.me/{numero_wa(o['vendeur']['telephone'])}?text="
                               + quote(f"Bonjour, c'est Le Black. Pour {o['code_vg']} ({o['titre']}), envoie-nous une courte vidéo qui montre l'objet en marche, sous tous les angles."))
            st.write(f"Catégorie : {CATEGORIES[o['categorie']]} · État annoncé : {ETATS[o['etat']]} · "
                     f"Prix demandé : {fcfa(o['prix_demande'])}")
            if o.get("description"):
                st.write(o["description"])
            k = o["id"]
            st.markdown("**Photos** (1 à 4, nettes, sur fond uni, défauts visibles)")
            montrer_photos(o.get("photos"))
            nouvelles = st.file_uploader("Prendre ou choisir des photos", type=["jpg", "jpeg", "png", "webp"],
                                         accept_multiple_files=True, key=f"ph{k}_{st.session_state.get('photos_n', 0)}")
            if nouvelles and st.button("📷 Enregistrer les photos", key=f"bph{k}"):
                with st.spinner("Envoi des photos…"):
                    envoyer_photos(o, nouvelles)
                st.session_state.photos_n = st.session_state.get("photos_n", 0) + 1
                ok(f"Photos de {o['code_vg']} enregistrées.")
            if partenaire:
                controles = [st.checkbox("Photos nettes et fidèles (au moins une)", key=f"phok{k}"),
                             st.checkbox("🎥 Vidéo de test reçue sur WhatsApp : l'objet fonctionne et correspond à la fiche", key=f"vid{k}")]
            else:
                controles = [st.checkbox("Pièce d'identité du vendeur vue", value=o["vendeur"]["piece_identite_vue"], key=f"pi{k}")]
            imei, preuve = None, False
            if o["est_appareil"] and not partenaire:
                imei = st.text_input("IMEI ou numéro de série", value=o.get("imei") or "", key=f"imei{k}")
                preuve = st.checkbox("Facture ou boîte présentée, même IMEI que l'appareil", key=f"pr{k}")
                controles += [preuve, st.checkbox("Testé : s'allume, charge, appels, caméra, écran, boutons", key=f"t{k}")]
            elif not partenaire:
                controles.append(st.checkbox("Objet complet, propre, conforme à la description", key=f"c{k}"))
            defauts = st.text_input("Défauts constatés (seront écrits dans l'annonce)", key=f"d{k}")
            etat = st.selectbox("État constaté", list(ETATS), format_func=ETATS.get,
                                index=list(ETATS).index(o["etat"]), key=f"e{k}")
            prix = st.number_input("Prix de vente retenu (FCFA)", min_value=0, step=500,
                                   value=int(o["prix_demande"] or 0), key=f"p{k}")
            c1, c2 = st.columns(2)
            if c1.button("✅ Conforme", key=f"ok{k}", type="primary"):
                if not all(controles):
                    st.error("Tous les contrôles doivent être cochés pour déclarer l'objet conforme.")
                elif not o.get("photos"):
                    st.error("Ajoute au moins une photo et clique sur « Enregistrer les photos » avant de déclarer l'objet conforme.")
                elif prix <= 0:
                    st.error("Indique le prix de vente.")
                else:
                    sb().table("objets").update({
                        "statut": "verifie", "etat": etat, "defauts": defauts or None, "imei": imei or None,
                        "preuve_achat": preuve, "prix_vente": int(prix), "verifie_par": membre()["id"],
                        "video_recue": partenaire,
                    }).eq("id", k).execute()
                    if not partenaire and controles[0] and not o["vendeur"]["piece_identite_vue"]:
                        sb().table("personnes").update({"piece_identite_vue": True}).eq("id", o["vendeur_id"]).execute()
                    ok(f"{o['code_vg']} vérifié : il attend la validation du garant.")
            motif = c2.text_input("Motif du refus", key=f"m{k}")
            if c2.button("❌ Refuser et rendre au vendeur", key=f"no{k}"):
                if not motif.strip():
                    st.error("Indique le motif du refus.")
                else:
                    sb().table("objets").update({"statut": "refuse", "motif_refus": motif.strip(),
                                                 "verifie_par": membre()["id"]}).eq("id", k).execute()
                    ok(f"{o['code_vg']} refusé. Préviens le vendeur et rends-lui l'objet.")


def page_publication():
    st.header("Publication")
    st.caption("Étape 3 : seul le garant (ou un admin) publie, après avoir relu la fiche.")
    if not est_garant():
        st.warning("Cette étape est réservée au garant et aux admins.")
        return
    objets = sb().table("objets").select("*, vendeur:personnes(nom)").eq("statut", "verifie").order("created_at").execute().data
    if not objets:
        st.success("Aucun objet en attente de publication.")
    for o in objets:
        with st.expander(f"{o['code_vg']} — {o['titre']} · {fcfa(o['prix_vente'])}", expanded=True):
            montrer_photos(o.get("photos"), largeur=200)
            st.code(texte_annonce(o), language=None)
            st.caption("Dans WhatsApp, joins ces photos à l'annonce (appui long sur une photo → enregistrer).")
            st.caption(f"Vendeur : {o['vendeur']['nom']} · Formule : {FORMULES[o['formule']]} · "
                       f"Commission prévue : {fcfa(commission(o['formule'], o['prix_vente'], o.get('taux_commission')))}"
                       + (" · 🤝 vendeur partenaire" if o.get("commercial_id") else ""))
            if st.button("Valider et publier", key=f"pub{o['id']}", type="primary"):
                sb().table("objets").update({"statut": "publie", "valide_par": membre()["id"]}).eq("id", o["id"]).execute()
                st.session_state.a_partager = o["id"]
                ok(f"{o['code_vg']} publié. Dernière étape : clique sur « 📲 Envoyer dans WhatsApp ».")

    st.subheader("En vente actuellement")
    en_vente = sb().table("objets").select("*").eq("statut", "publie").order("created_at", desc=True).execute().data
    a_partager = st.session_state.pop("a_partager", None)
    for o in en_vente:
        juste_publie = o["id"] == a_partager
        with st.expander(f"{o['code_vg']} — {o['titre']} · {fcfa(o['prix_vente'])}", expanded=juste_publie):
            montrer_photos(o.get("photos"), largeur=140)
            bouton_whatsapp(o, f"wa{o['id']}")
            st.code(texte_annonce(o), language=None)


def page_commandes():
    st.header("Commandes")
    st.caption("Étapes 4 à 6 : l'acheteur commande, paie Le Black, puis tu livres.")
    en_vente = sb().table("objets").select("id, code_vg, titre, prix_vente").eq("statut", "publie").order("code_vg").execute().data
    with st.expander("➕ Nouvelle commande", expanded=bool(en_vente)):
        if not en_vente:
            st.info("Aucun objet publié pour le moment.")
        else:
            choix = st.selectbox("Objet commandé", en_vente, format_func=lambda o: f"{o['code_vg']} — {o['titre']} ({fcfa(o['prix_vente'])})")
            pid, nouvelle = choisir_ou_creer_personne("acheteur", "Acheteur")
            c1, c2, c3 = st.columns(3)
            prix = c1.number_input("Prix (FCFA)", min_value=0, step=500, value=int(choix["prix_vente"]))
            frais = c2.number_input("Frais de livraison (FCFA)", min_value=0, step=100, value=500)
            mode = c3.selectbox("Paiement", ["mobile_money", "especes"],
                                format_func={"mobile_money": "Mobile Money", "especes": "Espèces à la livraison"}.get)
            if st.button("Enregistrer la commande", type="primary"):
                acheteur_id = enregistrer_personne(pid, nouvelle)
                sb().table("commandes").insert({"objet_id": choix["id"], "acheteur_id": acheteur_id, "prix": int(prix),
                                                "frais_livraison": int(frais), "mode_paiement": mode}).execute()
                sb().table("objets").update({"statut": "reserve"}).eq("id", choix["id"]).execute()
                ok(f"Commande enregistrée : écris « RÉSERVÉ » sous l'annonce {choix['code_vg']}.")

    commandes = sb().table("commandes").select("*, objet:objets(id, code_vg, titre, commercial_id, vendeur:personnes(nom, telephone), ville:villes(nom)), acheteur:personnes(nom, telephone)") \
        .in_("statut", ["reservee", "payee"]).order("created_at").execute().data
    st.subheader("À encaisser et à livrer")
    if not commandes:
        st.success("Aucune commande en cours.")
    for c in commandes:
        o = c["objet"]
        total = c["prix"] + c["frais_livraison"]
        etat = "💰 payée" if c["statut"] == "payee" else "⏳ pas encore payée"
        with st.expander(f"{o['code_vg']} — {o['titre']} → {c['acheteur']['nom']} ({c['acheteur']['telephone']}) · {fcfa(total)} · {etat}"):
            k = c["id"]
            if o.get("commercial_id"):
                part = o["vendeur"]
                st.info(f"🤝 Objet d'un vendeur partenaire ({o['ville']['nom']}) : c'est **{part['nom']}** qui livre. "
                        "L'acheteur paie toujours sur le compte de Le Black.")
                if c["statut"] == "payee":
                    st.link_button("💬 Demander la livraison au partenaire",
                                   f"https://wa.me/{numero_wa(part['telephone'])}?text="
                                   + quote(f"Bonjour, c'est Le Black. {o['code_vg']} ({o['titre']}) est payé. "
                                           f"Merci de le livrer à {c['acheteur']['nom']} ({c['acheteur']['telephone']}) "
                                           "et de cliquer sur « Livré » dans l'appli."))
            if c["statut"] == "reservee":
                ref = st.text_input("Référence Mobile Money (ou « espèces »)", key=f"ref{k}")
                b1, b2 = st.columns(2)
                if b1.button("Paiement reçu sur le compte de Le Black", key=f"pay{k}", type="primary"):
                    sb().table("commandes").update({"statut": "payee", "date_paiement": maintenant(),
                                                    "reference_paiement": ref or None}).eq("id", k).execute()
                    ok("Paiement enregistré.")
                if b2.button("Annuler la commande", key=f"ann{k}"):
                    sb().table("commandes").update({"statut": "annulee"}).eq("id", k).execute()
                    sb().table("objets").update({"statut": "publie"}).eq("id", o["id"]).execute()
                    ok(f"Commande annulée : {o['code_vg']} est de nouveau en vente.")
            else:
                if st.button("📦 Livré à l'acheteur (la garantie commence)", key=f"liv{k}", type="primary"):
                    sb().table("commandes").update({"statut": "livree", "date_livraison": maintenant(),
                                                    "livre_par": membre()["id"]}).eq("id", k).execute()
                    sb().table("objets").update({"statut": "vendu"}).eq("id", o["id"]).execute()
                    ok(f"{o['code_vg']} livré. Écris « VENDU » sous l'annonce.")


def page_garanties():
    st.header("Garanties et réclamations")
    st.caption("Étape 7 : pendant la garantie, l'acheteur peut signaler un problème.")
    maintenant_dt = datetime.now(timezone.utc)
    livrees = sb().table("commandes").select("*, objet:objets(id, code_vg, titre, est_appareil), acheteur:personnes(nom, telephone)") \
        .eq("statut", "livree").order("fin_garantie").execute().data
    sous_garantie = [c for c in livrees if parse_dt(c["fin_garantie"]) > maintenant_dt]
    st.subheader("Sous garantie")
    if not sous_garantie:
        st.info("Aucune vente sous garantie.")
    for c in sous_garantie:
        with st.expander(f"{c['objet']['code_vg']} — {c['objet']['titre']} → {c['acheteur']['nom']} · fin le {jolie_date(c['fin_garantie'])}"):
            motif = st.text_input("Problème signalé par l'acheteur", key=f"rec{c['id']}")
            st.caption("Rappel : un changement d'avis, l'usure indiquée ou une casse après livraison ne sont pas couverts.")
            if st.button("Enregistrer la réclamation", key=f"brec{c['id']}"):
                if not motif.strip():
                    st.error("Décris le problème.")
                else:
                    sb().table("reclamations").insert({"commande_id": c["id"], "motif": motif.strip()}).execute()
                    sb().table("commandes").update({"statut": "reclamation"}).eq("id", c["id"]).execute()
                    ok("Réclamation enregistrée. Le paiement du vendeur est bloqué.")

    st.subheader("Réclamations à trancher")
    if not est_garant():
        st.caption("Seul le garant ou un admin peut trancher.")
    recs = sb().table("reclamations").select("*, commande:commandes(id, prix, frais_livraison, objet:objets(id, code_vg, titre), acheteur:personnes(nom, telephone))") \
        .eq("decision", "en_attente").execute().data
    if not recs:
        st.success("Aucune réclamation en attente.")
    for r in recs:
        c = r["commande"]
        with st.expander(f"{c['objet']['code_vg']} — {c['acheteur']['nom']} : {r['motif']}", expanded=True):
            if est_garant():
                b1, b2 = st.columns(2)
                if b1.button(f"Accepter : rembourser {fcfa(c['prix'])} et reprendre l'objet", key=f"acc{r['id']}", type="primary"):
                    sb().table("reclamations").update({"decision": "acceptee", "traite_par": membre()["id"], "traitee_le": maintenant()}).eq("id", r["id"]).execute()
                    sb().table("commandes").update({"statut": "remboursee"}).eq("id", c["id"]).execute()
                    sb().table("objets").update({"statut": "rendu"}).eq("id", c["objet"]["id"]).execute()
                    ok("Réclamation acceptée : rembourse l'acheteur depuis le compte de Le Black et rends l'objet au vendeur.")
                if b2.button("Refuser (non couvert par la garantie)", key=f"ref{r['id']}"):
                    sb().table("reclamations").update({"decision": "refusee", "traite_par": membre()["id"], "traitee_le": maintenant()}).eq("id", r["id"]).execute()
                    sb().table("commandes").update({"statut": "livree"}).eq("id", c["id"]).execute()
                    ok("Réclamation refusée. Explique la raison à l'acheteur.")


def page_vendeurs_a_payer():
    st.header("Vendeurs à payer")
    st.caption("Étape 8 : garantie terminée sans réclamation → tu paies le vendeur, moins ta commission.")
    if not est_garant():
        st.warning("Cette étape est réservée au garant et aux admins.")
        return
    lignes = sb().table("vendeurs_a_payer").select("*").order("fin_garantie").execute().data
    if not lignes:
        st.success("Aucun vendeur à payer pour le moment.")
    for v in lignes:
        with st.expander(f"{v['vendeur']} ({v['telephone']}) — {v['code_vg']} {v['titre']} : {fcfa(v['montant_a_verser'])}", expanded=True):
            st.write(f"Prix de vente {fcfa(v['montant_vente'])} − commission {fcfa(v['commission'])} = **{fcfa(v['montant_a_verser'])}**")
            ref = st.text_input("Référence du transfert Mobile Money", key=f"pv{v['commande_id']}")
            if st.button(f"J'ai payé {fcfa(v['montant_a_verser'])}", key=f"bpv{v['commande_id']}", type="primary"):
                sb().table("paiements_vendeurs").insert({
                    "commande_id": v["commande_id"], "vendeur_id": v["vendeur_id"], "montant_vente": v["montant_vente"],
                    "commission": v["commission"], "montant_verse": v["montant_a_verser"],
                    "reference_paiement": ref or None, "paye_par": membre()["id"],
                }).execute()
                sb().table("commandes").update({"statut": "terminee"}).eq("id", v["commande_id"]).execute()
                sb().table("objets").update({"statut": "vendeur_paye"}).eq("id", v["objet_id"]).execute()
                ok(f"Paiement de {v['vendeur']} enregistré. Vente {v['code_vg']} terminée.")

    st.subheader("Paiements déjà faits")
    faits = sb().table("paiements_vendeurs").select("created_at, montant_vente, commission, montant_verse, reference_paiement, vendeur:personnes(nom)") \
        .order("created_at", desc=True).limit(50).execute().data
    if faits:
        df = pd.DataFrame([{"Date": jolie_date(p["created_at"]), "Vendeur": p["vendeur"]["nom"], "Vente": p["montant_vente"],
                            "Commission": p["commission"], "Versé": p["montant_verse"], "Référence": p["reference_paiement"]} for p in faits])
        st.dataframe(df, hide_index=True, width="stretch")
        st.metric("Commissions encaissées (50 derniers paiements)", fcfa(df["Commission"].sum()))


def numero_wa(tel):
    chiffres = "".join(c for c in (tel or "") if c.isdigit())
    if len(chiffres) == 10:
        chiffres = "225" + chiffres
    return chiffres


def page_propositions():
    st.header("Propositions de la vitrine")
    st.caption("Messages envoyés par le public : « Je veux vendre » et « Je cherche ».")
    filtre = st.radio("Afficher", ["À traiter", "Toutes"], horizontal=True, label_visibility="collapsed")
    req = sb().table("propositions").select("*").order("created_at", desc=True)
    if filtre == "À traiter":
        req = req.in_("statut", ["nouvelle", "contactee"])
    props = req.limit(100).execute().data
    if not props:
        st.success("Aucune proposition à traiter.")
    etiquettes = {"nouvelle": "🆕 Nouvelle", "contactee": "📞 Contactée", "traitee": "✅ Traitée", "ignoree": "🚫 Ignorée"}
    for pr in props:
        genre = "💰 Veut vendre" if pr["type"] == "vendre" else "🔎 Cherche"
        montant = f" · {'prix souhaité' if pr['type'] == 'vendre' else 'budget'} {fcfa(pr['prix'])}" if pr.get("prix") else ""
        with st.expander(f"{etiquettes[pr['statut']]} — {genre} : {pr['texte'][:50]} — {pr['nom']}",
                         expanded=pr["statut"] == "nouvelle"):
            st.write(f"**{pr['nom']}** · {pr['telephone']}" + (f" · {pr['quartier']}" if pr.get("quartier") else ""))
            st.write(f"{CATEGORIES.get(pr.get('categorie') or 'autre', 'Autre')}{montant}")
            st.info(pr["texte"])
            st.caption(f"Reçue le {jolie_date(pr['created_at'])}")
            if pr["type"] == "vendre":
                msg = f"Bonjour {pr['nom']}, c'est Le Black. Merci pour votre proposition ({pr['texte'][:60]}). Pouvez-vous nous envoyer une photo ?"
            else:
                msg = f"Bonjour {pr['nom']}, c'est Le Black. Nous avons bien noté votre recherche : {pr['texte'][:60]}."
            st.link_button("💬 Lui écrire sur WhatsApp", f"https://wa.me/{numero_wa(pr['telephone'])}?text={quote(msg)}")
            c1, c2, c3 = st.columns(3)
            k = pr["id"]
            if pr["statut"] == "nouvelle" and c1.button("📞 Contactée", key=f"pc{k}"):
                sb().table("propositions").update({"statut": "contactee", "traitee_par": membre()["id"]}).eq("id", k).execute()
                ok("Proposition marquée « contactée ».")
            if pr["statut"] in ("nouvelle", "contactee") and c2.button("✅ Traitée", key=f"pt{k}"):
                sb().table("propositions").update({"statut": "traitee", "traitee_par": membre()["id"]}).eq("id", k).execute()
                ok("Proposition traitée." + (" Pense à enregistrer le dépôt dans « Nouveau dépôt »." if pr["type"] == "vendre" else ""))
            if pr["statut"] in ("nouvelle", "contactee") and c3.button("🚫 Ignorer", key=f"pi{k}"):
                sb().table("propositions").update({"statut": "ignoree", "traitee_par": membre()["id"]}).eq("id", k).execute()
                ok("Proposition ignorée.")


def page_registre():
    st.header("Registre")
    st.caption("Chaque changement d'étape est noté automatiquement, avec la date et la personne.")
    objets = sb().table("objets").select("id, code_vg, titre, statut, prix_vente, vendeur:personnes(nom), ville:villes(nom)").order("id", desc=True).execute().data
    if objets:
        st.dataframe(pd.DataFrame([{"Code": o["code_vg"], "Ville": (o.get("ville") or {}).get("nom"), "Objet": o["titre"], "Vendeur": o["vendeur"]["nom"],
                                    "Prix": o["prix_vente"], "Étape": STATUTS_OBJET[o["statut"]]} for o in objets]),
                     hide_index=True, width="stretch")
        code = st.selectbox("Historique d'un objet", [o["code_vg"] for o in objets])
        oid = next(o["id"] for o in objets if o["code_vg"] == code)
        equipe = {e["user_id"]: e["nom"] for e in sb().table("equipe").select("user_id, nom").execute().data}
        mvts = sb().table("mouvements").select("*").eq("objet_id", oid).order("created_at").execute().data
        st.dataframe(pd.DataFrame([{"Date": jolie_date(m["created_at"]),
                                    "De": STATUTS_OBJET.get(m["statut_avant"], "—"),
                                    "Vers": STATUTS_OBJET[m["statut_apres"]],
                                    "Par": equipe.get(m["par_user"], "—")} for m in mvts]),
                     hide_index=True, width="stretch")
    else:
        st.info("Le registre est vide pour l'instant.")


def page_equipe():
    st.header("Équipe")
    equipe = sb().table("equipe").select("*").order("id").execute().data
    st.dataframe(pd.DataFrame([{"Nom": e["nom"], "E-mail": e["email"], "Rôle": ROLES[e["role"]],
                                "Commission": pct(e["taux_commission"]) if e["role"] == "commercial" else "",
                                "Compte relié": "oui" if e["user_id"] else "pas encore", "Actif": e["actif"]} for e in equipe]),
                 hide_index=True, width="stretch")
    if membre()["role"] != "garant" and membre()["role"] != "admin":
        return
    st.subheader("Ajouter un membre")
    with st.form("ajout_membre"):
        c1, c2, c3, c4 = st.columns(4)
        nom = c1.text_input("Nom")
        email = c2.text_input("E-mail")
        tel = c3.text_input("Téléphone")
        role = c4.selectbox("Rôle", ["verificateur", "livreur", "admin", "commercial"], format_func=ROLES.get)
        st.caption("Pour un **vendeur partenaire** d'une autre ville, remplis aussi :")
        c5, c6, c7 = st.columns(3)
        liste_villes = villes()
        ville = c5.selectbox("Sa ville", liste_villes, format_func=lambda v: v["nom"]) if liste_villes else None
        taux = c6.number_input("Ta commission sur ses ventes (%)", min_value=0, max_value=50, value=10, step=1)
        caution = c7.number_input("Caution versée (FCFA)", min_value=0, step=5000, value=0)
        if st.form_submit_button("Ajouter"):
            if not nom.strip() or not email.strip():
                st.error("Nom et e-mail obligatoires.")
            elif role == "commercial" and (not tel.strip() or ville is None):
                st.error("Pour un vendeur partenaire, le téléphone et la ville sont obligatoires.")
            else:
                ligne = {"nom": nom.strip(), "email": email.strip().lower(), "telephone": tel or None, "role": role}
                if role == "commercial":
                    fiche = sb().table("personnes").insert({"nom": nom.strip(), "telephone": tel.strip(),
                                                            "ville_id": ville["id"], "piece_identite_vue": True}).execute().data[0]
                    ligne.update({"ville_id": ville["id"], "personne_id": fiche["id"],
                                  "taux_commission": taux / 100, "caution_versee": int(caution)})
                sb().table("equipe").insert(ligne).execute()
                ok(f"{nom} ajouté. Il crée son mot de passe avec « Première connexion ».")
    st.subheader("Villes")
    st.write(", ".join(v["nom"] for v in villes()) or "Aucune ville.")
    with st.form("ajout_ville", clear_on_submit=True):
        nv = st.text_input("Nouvelle ville")
        if st.form_submit_button("Ajouter la ville") and nv.strip():
            sb().table("villes").insert({"nom": nv.strip()}).execute()
            ok(f"Ville « {nv.strip()} » ajoutée.")
    st.subheader("Activer ou désactiver")
    autres = [e for e in equipe if e["role"] != "garant"]
    if autres:
        e = st.selectbox("Membre", autres, format_func=lambda e: f"{e['nom']} ({'actif' if e['actif'] else 'inactif'})")
        if st.button("Désactiver" if e["actif"] else "Réactiver"):
            sb().table("equipe").update({"actif": not e["actif"]}).eq("id", e["id"]).execute()
            ok("Modification enregistrée.")


def page_partenaires():
    st.header("Vendeurs partenaires")
    st.caption("Les revendeurs des autres villes : ils stockent et livrent eux-mêmes ; tout le reste passe par toi.")
    if not est_garant():
        st.warning("Réservé au garant et aux admins.")
        return
    bilan = sb().table("bilan_partenaires").select("*").order("ville").execute().data
    if not bilan:
        st.info("Aucun vendeur partenaire. Ajoute-les dans la page « Équipe » (rôle « Vendeur partenaire »).")
        return
    st.dataframe(pd.DataFrame([{"Partenaire": b["nom"], "Ville": b["ville"], "Téléphone": b["telephone"],
                                "Commission": pct(b["taux_commission"]), "Caution": b["caution_versee"],
                                "Proposés": b["objets_proposes"], "En vente": b["en_vente"], "Vendus": b["vendus"],
                                "Tes commissions": b["commissions_gagnees"], "Versé au partenaire": b["verse_au_partenaire"],
                                "Actif": b["actif"]} for b in bilan]), hide_index=True, width="stretch")
    st.subheader("Modifier la caution ou la commission")
    b = st.selectbox("Partenaire", bilan, format_func=lambda b: f"{b['nom']} ({b['ville']})")
    c1, c2 = st.columns(2)
    caution = c1.number_input("Caution versée (FCFA)", min_value=0, step=5000, value=int(b["caution_versee"]))
    taux = c2.number_input("Commission (%)", min_value=0, max_value=50, step=1, value=round(float(b["taux_commission"]) * 100))
    st.caption("La nouvelle commission s'applique aux objets qu'il proposera ensuite, pas à ceux déjà en vente.")
    if st.button("Enregistrer"):
        sb().table("equipe").update({"caution_versee": int(caution), "taux_commission": taux / 100}).eq("id", b["partenaire_id"]).execute()
        ok("Modification enregistrée.")


# ---------- Écrans du vendeur partenaire ----------

def page_partenaire_accueil():
    m = membre()
    st.header(f"Bonjour {m['nom']} 👋")
    st.caption(f"Vendeur partenaire de Le Black · commission de Le Black : {pct(m['taux_commission'])}")
    objets = sb().table("objets").select("statut").execute().data
    a_livrer = sb().table("commandes").select("id").eq("statut", "payee").execute().data
    a_recevoir = sb().table("vendeurs_a_payer").select("montant_a_verser").execute().data
    compte = lambda *s: sum(1 for o in objets if o["statut"] in s)
    c = st.columns(4)
    c[0].metric("En attente de vérification", compte("propose", "verifie"))
    c[1].metric("En vente", compte("publie"))
    c[2].metric("À livrer", len(a_livrer))
    c[3].metric("À recevoir", fcfa(sum(x["montant_a_verser"] for x in a_recevoir)))
    st.markdown(
        "#### Comment ça marche\n"
        "1. **📥 Proposer un objet** : fiche + photos.\n"
        f"2. Envoie une **courte vidéo de test** de l'objet à Le Black sur WhatsApp ({NUMERO_AFFICHE}).\n"
        "3. Le garant vérifie et **publie** : l'objet apparaît sur la vitrine.\n"
        "4. L'acheteur paie **Le Black**. Quand c'est payé, l'objet apparaît dans **🚚 À livrer**.\n"
        "5. Tu livres, tu cliques sur **Livré** : la garantie commence.\n"
        "6. Après la garantie, tu es payé par Mobile Money : prix de vente − commission.\n\n"
        "**Règles** : ne jamais encaisser l'acheteur toi-même · garder l'objet en bon état jusqu'à la livraison · "
        "pendant la garantie, reprendre l'objet si le garant accepte une réclamation."
    )


def page_partenaire_proposer():
    m = membre()
    st.header("Proposer un objet")
    st.caption("L'objet reste chez toi. Le garant le vérifie sur tes photos et ta vidéo de test, puis le publie.")
    n = st.session_state.setdefault("prop_n", 0)
    c1, c2 = st.columns(2)
    titre = c1.text_input("Objet (marque et modèle)", key=f"pt{n}")
    categorie = c2.selectbox("Catégorie", list(CATEGORIES), format_func=CATEGORIES.get, key=f"pc{n}")
    description = st.text_area("Description (taille, couleur, accessoires, défauts…)", key=f"pd{n}")
    c3, c4 = st.columns(2)
    etat = c3.selectbox("État", list(ETATS), format_func=ETATS.get, index=1, key=f"pe{n}")
    prix = c4.number_input("Prix de vente souhaité (FCFA)", min_value=0, step=500, key=f"pp{n}")
    est_appareil = st.checkbox("Appareil électrique ou téléphone (garantie 7 jours)", value=categorie == "electronique", key=f"pa{n}_{categorie}")
    photos = st.file_uploader("Photos (1 à 4, nettes, fond uni)", type=["jpg", "jpeg", "png", "webp"],
                              accept_multiple_files=True, key=f"pf{n}")
    if prix:
        com = commission("partenaire", prix, m["taux_commission"])
        st.info(f"Si l'objet est vendu {fcfa(prix)} : commission {fcfa(com)}, tu reçois {fcfa(prix - com)}.")
    if st.button("Envoyer au garant", type="primary"):
        if not titre.strip() or not prix or not photos:
            st.error("Indique l'objet, le prix et au moins une photo.")
            st.stop()
        o = sb().table("objets").insert({
            "vendeur_id": m["personne_id"], "titre": titre.strip(), "description": description.strip() or None,
            "categorie": categorie, "etat": etat, "est_appareil": est_appareil,
            "prix_demande": int(prix), "prix_vente": int(prix),
        }).execute().data[0]
        with st.spinner("Envoi des photos…"):
            envoyer_photos(o, photos)
        st.session_state.prop_n = n + 1
        st.session_state.video_pour = o["code_vg"]
        ok(f"{o['code_vg']} envoyé au garant. Dernière étape : envoie la vidéo de test sur WhatsApp (bouton ci-dessous).")
    if code := st.session_state.get("video_pour"):
        st.link_button(f"🎥 Envoyer la vidéo de test de {code} sur WhatsApp",
                       f"https://wa.me/{NUMERO_WHATSAPP}?text=" + quote(f"Vidéo de test pour {code} :"), type="primary")


def page_partenaire_objets():
    st.header("Mes objets")
    objets = sb().table("objets").select("*").order("created_at", desc=True).execute().data
    if not objets:
        st.info("Tu n'as encore proposé aucun objet.")
    for o in objets:
        with st.expander(f"{o['code_vg']} — {o['titre']} · {fcfa(o['prix_vente'])} · {STATUTS_OBJET[o['statut']]}"):
            montrer_photos(o.get("photos"), largeur=140)
            if o["statut"] == "propose":
                st.caption("En attente de la vérification du garant.")
                if not o.get("video_recue"):
                    st.link_button("🎥 Envoyer la vidéo de test sur WhatsApp",
                                   f"https://wa.me/{NUMERO_WHATSAPP}?text=" + quote(f"Vidéo de test pour {o['code_vg']} :"))
            elif o["statut"] == "refuse":
                st.error(f"Refusé : {o.get('motif_refus') or 'voir avec le garant'}")
            elif o["statut"] == "publie":
                st.success("En vente sur la vitrine. Garde-le prêt à livrer.")


def page_partenaire_livraisons():
    st.header("À livrer")
    st.caption("L'acheteur a payé Le Black. Livre-le, puis clique sur « Livré ».")
    commandes = sb().table("commandes").select("*, objet:objets(id, code_vg, titre), acheteur:personnes(nom, telephone)") \
        .eq("statut", "payee").order("created_at").execute().data
    if not commandes:
        st.success("Rien à livrer pour le moment.")
    for c in commandes:
        o, a = c["objet"], c["acheteur"]
        with st.expander(f"{o['code_vg']} — {o['titre']} → {a['nom']} ({a['telephone']})", expanded=True):
            st.warning("Ne demande **aucun argent** à l'acheteur : il a déjà payé Le Black.")
            st.link_button("💬 Écrire à l'acheteur", f"https://wa.me/{numero_wa(a['telephone'])}?text="
                           + quote(f"Bonjour {a['nom']}, je livre votre commande {o['code_vg']} de Le Black. Où et quand puis-je passer ?"))
            if st.button("📦 Livré à l'acheteur", key=f"pl{c['id']}", type="primary"):
                sb().table("commandes").update({"statut": "livree", "date_livraison": maintenant(),
                                                "livre_par": membre()["id"]}).eq("id", c["id"]).execute()
                sb().table("objets").update({"statut": "vendu"}).eq("id", o["id"]).execute()
                ok(f"{o['code_vg']} livré. La garantie commence ; tu seras payé à la fin.")


def page_partenaire_paiements():
    st.header("Mes paiements")
    attente = sb().table("vendeurs_a_payer").select("*").execute().data
    st.subheader("Garantie terminée : paiement à venir")
    if attente:
        st.dataframe(pd.DataFrame([{"Objet": f"{v['code_vg']} {v['titre']}", "Vente": v["montant_vente"],
                                    "Commission": v["commission"], "Tu recevras": v["montant_a_verser"]} for v in attente]),
                     hide_index=True, width="stretch")
    else:
        st.caption("Rien en attente.")
    st.subheader("Déjà reçus")
    faits = sb().table("paiements_vendeurs").select("created_at, montant_vente, commission, montant_verse, reference_paiement") \
        .order("created_at", desc=True).execute().data
    if faits:
        st.dataframe(pd.DataFrame([{"Date": jolie_date(p["created_at"]), "Vente": p["montant_vente"], "Commission": p["commission"],
                                    "Reçu": p["montant_verse"], "Référence": p["reference_paiement"]} for p in faits]),
                     hide_index=True, width="stretch")
    else:
        st.caption("Aucun paiement pour le moment.")


# ---------- Application ----------

if "user" not in st.session_state:
    ecran_connexion()
    st.stop()

if "membre" not in st.session_state:
    charger_membre()

m = membre()
PAGES = {
    "🏠 Accueil": page_partenaire_accueil,
    "📥 Proposer un objet": page_partenaire_proposer,
    "📦 Mes objets": page_partenaire_objets,
    "🚚 À livrer": page_partenaire_livraisons,
    "💰 Mes paiements": page_partenaire_paiements,
} if est_partenaire() else {
    "📊 Tableau de bord": page_tableau_de_bord,
    "📨 Propositions": page_propositions,
    "📥 Nouveau dépôt": page_nouveau_depot,
    "🔍 Vérification": page_verification,
    "📢 Publication": page_publication,
    "🛒 Commandes": page_commandes,
    "🛡️ Garanties": page_garanties,
    "💸 Vendeurs à payer": page_vendeurs_a_payer,
    "📒 Registre": page_registre,
    "🤝 Partenaires": page_partenaires,
    "👥 Équipe": page_equipe,
}
with st.sidebar:
    logo(grand=False)
    st.write(f"{m['nom']} · {ROLES[m['role']]}")
    page = st.radio("Menu", list(PAGES), label_visibility="collapsed")
    if st.button("Se déconnecter"):
        deconnexion()

if msg := st.session_state.pop("flash", None):
    st.success(msg)

PAGES[page]()
