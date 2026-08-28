#!/usr/bin/env bash
set -euo pipefail

REPO_NAME="${1:-piper-x-linux-controller}"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required. Install it with: sudo apt update && sudo apt install -y git"
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is required. Install it with:"
  echo "  sudo apt update && sudo apt install -y gh"
  exit 1
fi

if ! gh auth status --hostname github.com >/dev/null 2>&1; then
  echo "Opening GitHub browser/device authorization..."
  gh auth login --hostname github.com --git-protocol https --web
fi

OWNER="$(gh api user --jq .login)"
NOREPLY_EMAIL="$(gh api user --jq '.id|tostring')+${OWNER}@users.noreply.github.com"

git init >/dev/null
git branch -M main
git config user.name "${OWNER}"
git config user.email "${NOREPLY_EMAIL}"
git add .
if ! git diff --cached --quiet; then
  git commit -m "Initial PiPER X Linux controller"
fi

FULL_REPO="${OWNER}/${REPO_NAME}"
if gh repo view "${FULL_REPO}" >/dev/null 2>&1; then
  echo "Repository ${FULL_REPO} already exists; pushing to it."
  if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "https://github.com/${FULL_REPO}.git"
  else
    git remote add origin "https://github.com/${FULL_REPO}.git"
  fi
  git push -u origin main
else
  echo "Creating private repository ${FULL_REPO} and pushing..."
  gh repo create "${FULL_REPO}" --private --source=. --remote=origin --push
fi

echo "Uploaded: https://github.com/${FULL_REPO}"
