#!/usr/bin/env bash
# One-command owner setup on the VPS: asks for private values (never echoed),
# writes /opt/rizpram-fitness-bot/.env and supabase-ca.crt with the required
# ownership/permissions, then runs the tested deploy.sh for the given commit.
# Usage: sudo bash setup.sh <tested 40-character SHA>
set -Eeuo pipefail
BASE=/opt/rizpram-fitness-bot
SHA="${1:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Provide exact tested Git commit SHA."; exit 2; }
[[ "$(id -u)" == 0 ]] || { echo "Jalankan dengan sudo."; exit 2; }
[[ ! -L "$BASE" ]] || { echo "Deployment root must not be a symlink."; exit 2; }
mkdir -p "$BASE"
chown root:root "$BASE"
chmod 755 "$BASE"

if [[ -f "$BASE/.env" ]]; then
    echo "$BASE/.env sudah ada; dipakai apa adanya."
else
    echo "Isian tidak ditampilkan di layar dan tidak dikirim ke mana pun selain file .env di server ini."
    read -rsp "Token bot Telegram (dari @BotFather): " token; echo
    [[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]] || { echo "Format token tidak valid."; exit 2; }
    read -rp "User ID Telegram kamu (angka, dari @userinfobot): " uid
    [[ "$uid" =~ ^[1-9][0-9]{4,}$ ]] || { echo "User ID harus angka."; exit 2; }
    read -rsp "Supabase Session pooler URI (port 5432, password sudah diisi): " dburl; echo
    [[ "$dburl" =~ ^postgres(ql)?://postgres\.lzfrfpokshfrbnbaiuqo:[^@]+@[a-z0-9.-]+\.pooler\.supabase\.com:5432/postgres$ ]] || {
        echo "URI harus Session pooler (port 5432) project lzfrfpokshfrbnbaiuqo."; exit 2
    }
    [[ "$dburl" != *"'"* ]] || { echo "Password berisi tanda kutip tunggal; ganti password database dulu."; exit 2; }
    read -rsp "Gemini API key (opsional, Enter untuk lewati): " gemini; echo
    ai=false
    [[ -n "$gemini" ]] && ai=true
    tmp="$(mktemp "$BASE/.env.XXXXXX")"
    chmod 600 "$tmp"
    cat > "$tmp" <<EOF
TELEGRAM_BOT_TOKEN=$token
TELEGRAM_ALLOWED_USER_ID=$uid
DATABASE_URL='$dburl'
DATABASE_CA_FILE=/run/secrets/supabase-ca.crt
GEMINI_API_KEY=$gemini
AI_VISION_ENABLED=$ai
AI_FOOD_TEXT_ENABLED=$ai
AI_COACH_ENABLED=$ai
EOF
    unset token dburl gemini
    chown root:root "$tmp"
    mv "$tmp" "$BASE/.env"
    echo "Tersimpan: $BASE/.env (root, 600)."
fi

if [[ -f "$BASE/supabase-ca.crt" ]] && grep -q -- '-----BEGIN CERTIFICATE-----' "$BASE/supabase-ca.crt"; then
    echo "$BASE/supabase-ca.crt sudah ada; dipakai apa adanya."
else
    echo "Supabase → Project Settings → Database → SSL Configuration → Download certificate."
    echo "Buka file itu, salin seluruh isinya, tempel di sini (akan berhenti otomatis setelah END CERTIFICATE):"
    pem=""
    while IFS= read -r line; do
        pem+="$line"$'\n'
        [[ "$line" == *"-----END CERTIFICATE-----"* ]] && break
    done
    [[ "$pem" == *"-----BEGIN CERTIFICATE-----"* ]] || { echo "Bukan sertifikat PEM."; exit 2; }
    printf '%s' "$pem" > "$BASE/supabase-ca.crt"
    echo "Tersimpan: $BASE/supabase-ca.crt (root, 644)."
fi
chown root:root "$BASE/.env" "$BASE/supabase-ca.crt"
chmod 600 "$BASE/.env"
chmod 644 "$BASE/supabase-ca.crt"

echo "Menjalankan deploy.sh untuk $SHA. Saat diminta, kirim /start lalu /target ke bot."
deploy="$(mktemp)"
curl --proto '=https' --tlsv1.2 -fsSL "https://raw.githubusercontent.com/rizpram/repit/$SHA/scripts/deploy.sh" -o "$deploy"
exec bash "$deploy" "$SHA"
