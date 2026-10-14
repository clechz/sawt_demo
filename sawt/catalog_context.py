"""Read-only bounded retrieval before planning; never selects or mutates an item."""
import re
from .domain import normalize, BRANCHES


def retrieve(menu, text, state):
    normalized=normalize(text)
    caller_words=set(normalized.split())
    name_words=[set(normalize(item['name']).split()) | set(normalize(item['name_en']).split()) for item in menu.items.values()]
    last_question=next((h['content'] for h in reversed(state['history']) if h['role']=='assistant'),'')
    # Short answers such as "دجاج ساندويتش" refer to the dish we just asked
    # about. Prior words aid retrieval only; they never authorize selections.
    if len(normalized.split())<=10 and ('؟' in last_question or '?' in last_question):
        normalized+=' '+normalize(last_question)
    # Name vocabulary only, not option words/categories that could turn a
    # short size answer into a broad unrelated menu search.
    vocabulary={word for item in menu.items.values() for label in (item['name'],item['name_en'])
                for word in normalize(label).split() if len(word)>=3}
    ignored={'with','and','the','بال','بدون','كبير','صغير','عادي','وجبة','وجبه'}
    terms=[]
    for word in normalized.split():
        forms=[word]
        if word.startswith(('و','ب')):forms.append(word[1:])
        if word.startswith('ال'):forms.append(word[2:])
        matched=next((v for v in forms if v in vocabulary and v not in ignored),None)
        if matched and matched not in terms:terms.append(matched)
    result={}
    # A single substituted character can hide a dish while its bread still
    # matches. Supply possibilities as evidence, never rewrite caller intent.
    suggestions=[]
    for word in sorted(caller_words):
        if len(word)<5 or word in vocabulary:
            continue
        near=[term for term in sorted(vocabulary)
              if len(term)==len(word) and sum(a!=b for a,b in zip(term,word))==1]
        if len(near)==1:
            matches=menu.search(near[0],state['branch'],limit=3)
            suggestions.append({'heard':word,'possible_name_word':near[0],
                                'items':matches['items']})
    if suggestions:
        result['possible_mishearings']=suggestions[:3]
        result['mishearing_warning']='Read-only spelling candidates, not selections. Interpret the whole request; clarify if uncertain. A following bread word can be an option of this dish, not a separate ordered item.'
    if terms:
        result['menu_candidates']=menu.search(' '.join(terms),state['branch'],limit=5)
        result['matched_words']=terms
        result['unique_current_name_word']=any(word in caller_words and sum(word in names for names in name_words)==1 for word in terms)
        result['candidate_warning']='Candidates only. Unmatched caller words still matter. This does NOT prove the exact requested dish exists; never silently substitute. Retrieve further if needed.'
    if any(normalize(b['name']).replace('فرع ','') in normalized or
           any(normalize(zone) in normalized for zone in b['zones']) for b in BRANCHES.values()):
        result['branches']=BRANCHES
    return result
