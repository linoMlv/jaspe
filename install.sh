#!/usr/bin/env bash
set -e

# Définition des couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}=====================================${NC}"
echo -e "${BLUE}        Jaspe - Installation         ${NC}"
echo -e "${BLUE}=====================================${NC}\n"

# 1. Audit système
echo -e "${YELLOW}>> Audit du système...${NC}"
if ! command -v curl >/dev/null 2>&1; then
    echo -e "${RED}Erreur : 'curl' est requis pour l'installation.${NC}"
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    echo -e "${RED}Erreur : 'git' est requis pour cloner le projet.${NC}"
    exit 1
fi

# Configuration des chemins
INSTALL_DIR="$HOME/.jaspe-cli"
UV_BIN="$HOME/.local/bin/uv"

# 2. Gestion de UV
echo -e "${YELLOW}>> Vérification de l'environnement Python 'uv'...${NC}"
if command -v uv >/dev/null 2>&1; then
    UV_CMD=$(command -v uv)
    echo -e "${GREEN}✓ uv est déjà installé (${UV_CMD}).${NC}"
elif [ -f "$UV_BIN" ]; then
    UV_CMD="$UV_BIN"
    echo -e "${GREEN}✓ uv trouvé dans $UV_BIN.${NC}"
else
    echo -e "${BLUE}L'utilitaire 'uv' est manquant. Installation automatique en cours...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    UV_CMD="$UV_BIN"
    export PATH="$HOME/.local/bin:$PATH"
    echo -e "${GREEN}✓ uv a été installé avec succès.${NC}"
fi

# 3. Synchronisation Git
echo -e "${YELLOW}>> Synchronisation de l'outil Jaspe...${NC}"
REPO_URL="${JASPE_REPO_URL:-https://github.com/linomlv/jaspe.git}"
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${BLUE}Préparation de la mise à jour...${NC}"
    cd "$INSTALL_DIR"
    git pull origin main --quiet
else
    echo -e "${BLUE}Clonage du dépôt Jaspe vers $INSTALL_DIR...${NC}"
    git clone "$REPO_URL" "$INSTALL_DIR" --quiet
fi

# 4. Installation via uv tool
echo -e "${YELLOW}>> Installation système de l'exécutable...${NC}"
"$UV_CMD" tool install --force -e "$INSTALL_DIR" > /dev/null

echo -e "\n${GREEN}=================================================${NC}"
echo -e "${GREEN}   ✨ INSTALLATION DE JASPE TERMINÉE AVEC SUCCÈS !   ${NC}"
echo -e "${GREEN}=================================================${NC}\n"

# Ajout dynamique de PATH pour le shell courant si non existant
if ! command -v jaspe >/dev/null 2>&1; then
    echo -e "${YELLOW}Info :${NC} Jaspe vient d'être installé mais n'est pas encore dans votre PATH."
    echo -e "Veuillez redémarrer votre terminal ou exécuter :"
    echo -e "  ${BLUE}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}\n"
    
    # Exécution via le chemin absolu pour le test final
    "$HOME/.local/bin/jaspe" --help | head -n 5
else
    jaspe --help | head -n 5
fi

echo -e "\n${BLUE}Tapez 'jaspe --help' pour démarrer une application.${NC}"
