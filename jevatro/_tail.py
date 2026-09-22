import io
t = io.open("logs/batch20_console.txt", encoding="utf-8", errors="replace").read()
print(len(t))
print(t[-2000:])
