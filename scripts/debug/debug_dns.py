import socket

HOST = "db.zxgksjwszqqvwoyfrekw.supabase.co"

print(f"Resolving {HOST}...")
try:
    infos = socket.getaddrinfo(HOST, 5432)
    for info in infos:
        family, socktype, proto, canonname, sockaddr = info
        family_name = "IPv6" if family == socket.AF_INET6 else "IPv4"
        print(f"- {family_name}: {sockaddr}")
except Exception as e:
    print(f"Error resolving: {e}")
