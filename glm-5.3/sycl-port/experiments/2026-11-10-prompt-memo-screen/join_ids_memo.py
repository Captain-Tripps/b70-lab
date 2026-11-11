def join_ids_memo(memo: dict, ids, block: int = 4096) -> str:
    """','.join of ids (MAYA_PROMPT_MEMO), the blocks that start as the last prompt's taken from its string."""
    ids = [int(t) for t in ids] if not isinstance(ids, list) else ids
    last, text, offs = memo.get("ids", ()), memo.get("text", ""), memo.get("offs", ())
    k = 0
    while k < len(offs) and (k + 1) * block <= min(len(ids), len(last)) and \
            ids[k * block:(k + 1) * block] == last[k * block:(k + 1) * block]:
        k += 1
    head, new_offs = text[:offs[k - 1]] if k else "", list(offs[:k])
    parts, at = [head] if k else [], len(head)
    for i in range(k * block, len(ids), block):
        s = ",".join(map(str, map(int, ids[i:i + block])))
        if at:
            s = "," + s
        parts.append(s)
        at += len(s)
        if i + block <= len(ids):
            new_offs.append(at)
    out = "".join(parts)
    memo.update(ids=list(ids), text=out, offs=new_offs)
    return out
