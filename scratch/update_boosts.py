with open('server/deck_data.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('"boost_score": 15', '"boost_score": 8')
text = text.replace('"boost_score": 12', '"boost_score": 8')
text = text.replace('(+15%)', '(+8%)')
text = text.replace('(+12%)', '(+8%)')
text = text.replace('boost_score = outcome.get("boost_score", 10)', 'boost_score = outcome.get("boost_score", 8)')

with open('server/deck_data.py', 'w', encoding='utf-8') as f:
    f.write(text)

print('Updated boost_score and boost texts!')
