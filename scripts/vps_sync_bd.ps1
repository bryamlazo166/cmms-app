# Sincroniza la BD del VPS desde Supabase (refresh completo, manual).
# Consume egress de Supabase SOLO al ejecutarse (~5-30 MB). Deja backup fechado
# en ~/cmms/backups del VPS.
$key = "$env:USERPROFILE\.ssh\id_cmms_vps"
ssh -i $key bryam16@51.79.11.222 "bash ~/cmms/app/deploy/vps/sync_from_supabase.sh"
