def chunk(lst, n):
    out = []
    for i in range(0, len(lst) // n * n, n):
        out.append(lst[i:i + n])
    return out
