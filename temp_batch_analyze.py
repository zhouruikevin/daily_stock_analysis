#!/usr/bin/env python3
"""批量分析关注股票"""

from analyzer_service import analyze_stocks

stocks = ['603296', '603444', '601138', '300750', '600879', '601899', '002460', '600089']
print(f'开始分析 {len(stocks)} 只股票...\n')

results = analyze_stocks(stocks, notifier=None)

print('\n' + '='*80)
print('股票分析结果汇总')
print('='*80 + '\n')

for result in results:
    if result:
        code = result.code
        name = result.name
        dashboard = result.dashboard
        
        # 核心结论
        core = dashboard.get('core_conclusion', {})
        one_sentence = core.get('one_sentence', 'N/A')
        signal = core.get('signal_type', 'N/A')
        
        # 狙击点
        battle = dashboard.get('battle_plan', {})
        sniper = battle.get('sniper_points', {})
        buy_price = sniper.get('ideal_buy', 'N/A')
        stop_loss = sniper.get('stop_loss', 'N/A')
        target = sniper.get('take_profit', 'N/A')
        
        # 其他指标
        sentiment = result.sentiment_score
        advice = result.operation_advice
        confidence = result.confidence_level
        
        print(f'📊 {name} ({code})')
        print(f'💡 核心结论: {one_sentence}')
        print(f'🎯 狙击点: 买入 ¥{buy_price} | 止损 ¥{stop_loss} | 目标 ¥{target}')
        print(f'📈 情绪得分: {sentiment}/100')
        print(f'💼 操作建议: {advice}')
        print(f'🎲 置信度: {confidence}')
        print('-' * 80)
        print()

print('='*80)
print('分析完成!')
print('='*80)
