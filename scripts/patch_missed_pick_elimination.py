from pathlib import Path

p = Path('index.html')
s = p.read_text()

replacements = [
    (
        "revealed.push(row?row.revealed:false);",
        "revealed.push(row?row.revealed:!!(weekDeadline(w)&&new Date()>=weekDeadline(w)));",
    ),
    (
        "if(revealed[w]&&results[w]===0){eliminatedWeek=w+1;break;}",
        "if((!picks[w]&&weekDeadline(w+1)&&new Date()>=weekDeadline(w+1))||(revealed[w]&&results[w]===0)){eliminatedWeek=w+1;break;}",
    ),
    (
        "if(!mine){const prev=weeks[i-1];",
        "if(!mine){const deadline=weekDeadline(w);if(deadline&&now>=deadline)return{state:'eliminated',eliminatedWeek:w};const prev=weeks[i-1];",
    ),
]

for old, new in replacements:
    count = s.count(old)
    if count != 1:
        raise SystemExit(f'Expected exactly one match, found {count}: {old}')
    s = s.replace(old, new, 1)

p.write_text(s)
