from pathlib import Path

p = Path('index.html')
s = p.read_text()

replacements = [
    (
        "return `<span class=\"opponent-context\">(${isAway?'@':'vs.'} ${opponent})</span>`;",
        "return `<span class=\"opponent-context\">${isAway?'@':'vs.'} ${opponent}</span>`;",
    ),
    (
        "const pick=p.picks[w],revealed=p.revealed[w],result=p.results[w],opp=pick?opponentOf(w+1,pick):null;",
        "const pick=p.picks[w],revealed=p.revealed[w],result=p.results[w],game=pick?gameFor(w+1,pick):null,opp=pick?opponentOf(w+1,pick):null;",
    ),
    (
        "const label=revealed?(pick?`${pick}${opp?` <span class=\"opp-context\">(vs ${opp})</span>`:''}`:'No pick'):'Hidden until Sat 11am',lost=revealed&&result===0;",
        "const label=revealed?(pick?`${pick}${opp?` <span class=\"opp-context\">${game&&game.away===pick?'@':'vs.'} ${opp}</span>`:''}`:'No pick'):'Hidden until Sat 11am',lost=revealed&&result===0;",
    ),
]

for old, new in replacements:
    count = s.count(old)
    if count != 1:
        raise SystemExit(f'Expected exactly one match, found {count}: {old}')
    s = s.replace(old, new, 1)

p.write_text(s)
