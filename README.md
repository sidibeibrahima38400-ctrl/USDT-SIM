# USDT_SIM — application de démonstration

Application Flask + SQLite pour simuler un jeton interne nommé `USDT_SIM`.
**Ce projet ne crée pas de vrais USDT, ne déploie pas de contrat Tether et ne se connecte à aucune blockchain.**
Les soldes sont des données locales de démonstration, sans valeur monétaire.

## Fonctionnalités
- Création de comptes de démonstration
- Connexion avec mots de passe hachés
- Tableau de bord et historique
- Émission fictive réservée à l'administrateur
- Transferts internes simulés
- Protection CSRF, requêtes SQL paramétrées, cookies de session HttpOnly/SameSite
- Montants traités avec `Decimal` et six décimales

## Installation (Python 3.10+)

```bash
python -m venv .venv
# Windows : .venv\Scripts\activate
# macOS / Linux :
source .venv/bin/activate
pip install -r requirements.txt
```

Configurez au minimum les variables d'environnement avant le premier lancement :

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="choisir-un-mot-de-passe-long-et-unique"
python app.py
```

Sous Windows PowerShell, utilisez `$env:SECRET_KEY="..."`, `$env:ADMIN_USERNAME="admin"` et `$env:ADMIN_PASSWORD="..."`.

Ouvrez ensuite http://127.0.0.1:5000 dans votre navigateur. Connectez-vous avec les identifiants administrateur définis. Créez d'autres comptes via « Créer un compte », puis utilisez l'écran admin pour créditer des unités fictives.

## Déploiement
Ne lancez pas le serveur de développement Flask sur Internet. Pour un usage interne, utilisez un serveur WSGI (par exemple Waitress ou Gunicorn), HTTPS, une clé secrète forte, `COOKIE_SECURE=1`, une base de données sauvegardée et des protections de débit au niveau du reverse proxy. Faites réaliser un audit avant toute exposition publique.

## Limites
- Aucun vrai USDT ni valeur en dollars/euros.
- Aucun portefeuille crypto, clé privée, dépôt, retrait ou échange.
- Les opérations sont centralisées dans SQLite et modifiables par l'administrateur de la base.
- Le nom `USDT_SIM` est volontairement distinct de la marque et du jeton USDT de Tether.
