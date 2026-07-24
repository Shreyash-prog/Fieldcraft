def chunk(lst, n):
    if n < 1:
        raise ValueError("n must be >= 1")
    return [lst[i:i + n] for i in range(0, len(lst), n)]
