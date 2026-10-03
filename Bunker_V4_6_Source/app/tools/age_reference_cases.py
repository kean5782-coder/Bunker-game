#!/usr/bin/env python3
"""Deterministic illustrative care calculations, not samples of real human health."""
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from server.balance import CONFIG,effects_for_card,evaluate_survival
from server.age_balance import calculate_age_care


def cards(age,severity='medium',endurance=False,skills=None):
    return {'gender':{'age':age},'health':{'severity':severity,'mechanics':{}},
            'body':{'mechanics':{'traits':['endurance'] if endurance else []}},
            'profession':{'mechanics':{'skills':skills or {}}}}


def case(ages,good=False,fit=False,med=0,social=0,duration=5):
    people=[(str(i),f'Персонаж {i+1}',cards(age,'good' if good else 'medium',fit),True) for i,age in enumerate(ages)]
    return calculate_age_care(people,{'medicine':{'coverage':med},'social':{'coverage':social}},
                              duration,effects_for_card,CONFIG['age_care'])


def main():
    table=[{'age':age,'one_in_team_of_three_no_relief':case([age,30,30])['penalty']} for age in (55,60,65,70,75,80,90)]
    scenarios=[('Один 70-летний в тройке, без компенсаций',case([70,30,30])),
       ('Тот же возраст, хорошее здоровье',case([70,30,30],good=True)),
       ('То же плюс выносливость',case([70,30,30],good=True,fit=True)),
       ('То же плюс медицина 50% и организация 50%',case([70,30,30],good=True,fit=True,med=.5,social=.5)),
       ('Трое 70-летних, без компенсаций',case([70,70,70])),
       ('Трое 70-летних, здоровье, выносливость, помощь 50%/50%',case([70,70,70],good=True,fit=True,med=.5,social=.5)),
       ('Трое 90-летних, без компенсаций, проверка предела',case([90,90,90]))]
    ps=[{'id':'a','cards':cards(30,skills={'engineering':1})},{'id':'b','cards':cards(30,skills={'food':1})}]
    old=ps+[{'id':'c','cards':cards(70,'good',True,{'medicine':1})}]
    young=ps+[{'id':'c','cards':cards(25,'good',True)}]
    cat={'duration_years':5};bunk={'capacity':3,'initial_capacity':3,'supplies_years':5}
    report={'note':'Artificial controlled fixtures: medium health unless specified, no traits unless specified; 5-year isolation. Coverage values are inputs, not simulated achievements.',
      'age_table':table,'scenarios':[{'name':name,'care':care} for name,care in scenarios],
      'specialist_tradeoff':{'old_doctor':evaluate_survival(old,cat,bunk),'young_unskilled':evaluate_survival(young,cat,bunk)}}
    dest=ROOT/'age_results/reference_cases.json';dest.parent.mkdir(exist_ok=True,parents=True)
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'table':table,'cases':[(n,c['penalty']) for n,c in scenarios],
                     'old_doctor':report['specialist_tradeoff']['old_doctor']['survival_score'],
                     'young_unskilled':report['specialist_tradeoff']['young_unskilled']['survival_score']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
