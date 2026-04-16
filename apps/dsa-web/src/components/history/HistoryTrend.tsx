import type React from 'react';
import { useEffect, useState, useCallback } from 'react';
import type { HistoryTrendItem } from '../../types/analysis';
import { historyApi } from '../../api/history';
import { DashboardPanelHeader, DashboardStateBlock } from '../dashboard';

interface HistoryTrendProps {
  stockCode: string;
  stockName?: string;
  days?: number;
  className?: string;
}

/**
 * 格式化涨跌幅：正值红、负值绿、null 显示 --
 */
const formatPct = (value: number | null | undefined): { text: string; className: string } => {
  if (value === null || value === undefined) {
    return { text: '--', className: 'text-muted-text' };
  }
  const prefix = value > 0 ? '+' : '';
  const color = value > 0
    ? 'text-red-500 dark:text-red-400'
    : value < 0
      ? 'text-green-600 dark:text-green-400'
      : 'text-muted-text';
  return { text: `${prefix}${value.toFixed(2)}%`, className: color };
};

/**
 * 格式化数值型指标：null 显示 --
 */
const formatNum = (value: number | null | undefined, suffix = ''): { text: string; className: string } => {
  if (value === null || value === undefined) {
    return { text: '--', className: 'text-muted-text' };
  }
  return { text: `${value.toFixed(2)}${suffix}`, className: 'text-foreground' };
};

/**
 * 分析结果标签颜色
 */
const getAdviceStyle = (advice?: string): string => {
  if (!advice) return 'text-muted-text';
  const a = advice.toLowerCase();
  if (['买入', '加仓', '看多'].some(k => a.includes(k))) return 'text-red-500 dark:text-red-400';
  if (['卖出', '减仓', '看空'].some(k => a.includes(k))) return 'text-green-600 dark:text-green-400';
  return 'text-foreground';
};

/**
 * 历史趋势表格组件
 * 展示股票近 N 天分析变化趋势
 */
export const HistoryTrend: React.FC<HistoryTrendProps> = ({
  stockCode,
  stockName,
  days = 30,
  className = '',
}) => {
  const [items, setItems] = useState<HistoryTrendItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTrend = useCallback(async () => {
    if (!stockCode) return;
    setIsLoading(true);
    setError(null);
    try {
      const resp = await historyApi.getTrend(stockCode, days);
      setItems(resp.items);
    } catch (err) {
      setError('加载趋势数据失败');
      console.error('Failed to fetch history trend:', err);
    } finally {
      setIsLoading(false);
    }
  }, [stockCode, days]);

  useEffect(() => {
    void fetchTrend();
  }, [fetchTrend]);

  if (!stockCode) return null;

  return (
    <div className={`glass-card overflow-hidden ${className}`}>
      <DashboardPanelHeader
        className="px-4 pt-4 pb-2"
        title="历史趋势"
        titleClassName="text-sm font-medium"
        leading={
          <svg className="h-4 w-4 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
        }
        actions={
          <span className="text-[11px] text-muted-text">
            {stockName || stockCode} · 近{days}天
          </span>
        }
      />

      {isLoading ? (
        <div className="px-4 pb-4">
          <DashboardStateBlock loading compact title="加载趋势数据..." />
        </div>
      ) : error ? (
        <div className="px-4 pb-4 text-sm text-danger">{error}</div>
      ) : items.length === 0 ? (
        <div className="px-4 pb-4">
          <DashboardStateBlock
            compact
            title="暂无趋势数据"
            description="该股票尚无历史分析记录"
          />
        </div>
      ) : (
        <div className="overflow-x-auto px-4 pb-4">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-subtle text-muted-text">
                <th className="py-2 px-2 text-left font-medium whitespace-nowrap">时间</th>
                <th className="py-2 px-2 text-left font-medium whitespace-nowrap">分析结果</th>
                <th className="py-2 px-2 text-center font-medium whitespace-nowrap">分数</th>
                <th className="py-2 px-2 text-right font-medium whitespace-nowrap">涨跌幅</th>
                <th className="py-2 px-2 text-right font-medium whitespace-nowrap">量比</th>
                <th className="py-2 px-2 text-right font-medium whitespace-nowrap">换手率</th>
                <th className="py-2 px-2 text-right font-medium whitespace-nowrap">中证2000</th>
                <th className="py-2 px-2 text-right font-medium whitespace-nowrap">创业板</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const changePct = formatPct(item.changePct);
                const csi2000 = formatPct(item.indexCsi2000Pct);
                const chinext = formatPct(item.indexChinextPct);
                const volRatio = formatNum(item.volumeRatio);
                const turnover = formatNum(item.turnoverRate, '%');
                const adviceText = item.operationAdvice
                  ? `${item.operationAdvice}${item.trendPrediction ? `(${item.trendPrediction})` : ''}`
                  : '--';

                return (
                  <tr key={item.date} className="border-b border-subtle/50 hover:bg-hover/30 transition-colors">
                    <td className="py-2 px-2 whitespace-nowrap text-muted-text">{item.date}</td>
                    <td className={`py-2 px-2 whitespace-nowrap font-medium ${getAdviceStyle(item.operationAdvice)}`}>
                      {adviceText}
                    </td>
                    <td className="py-2 px-2 text-center whitespace-nowrap">
                      {item.sentimentScore !== null && item.sentimentScore !== undefined
                        ? item.sentimentScore
                        : '--'}
                    </td>
                    <td className={`py-2 px-2 text-right whitespace-nowrap font-mono ${changePct.className}`}>
                      {changePct.text}
                    </td>
                    <td className={`py-2 px-2 text-right whitespace-nowrap font-mono ${volRatio.className}`}>
                      {volRatio.text}
                    </td>
                    <td className={`py-2 px-2 text-right whitespace-nowrap font-mono ${turnover.className}`}>
                      {turnover.text}
                    </td>
                    <td className={`py-2 px-2 text-right whitespace-nowrap font-mono ${csi2000.className}`}>
                      {csi2000.text}
                    </td>
                    <td className={`py-2 px-2 text-right whitespace-nowrap font-mono ${chinext.className}`}>
                      {chinext.text}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
