# Actualiza el codigo del CMMS en el VPS desde GitHub (git pull + rebuild Docker).
$key = "$env:USERPROFILE\.ssh\id_cmms_vps"
ssh -i $key bryam16@51.79.11.222 "bash ~/cmms/app/deploy/vps/update_app.sh"
