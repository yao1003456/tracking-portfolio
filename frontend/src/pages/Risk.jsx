import { useState, useEffect } from 'react';
import { getRisk } from '../api';

export default function Risk() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await getRisk();
      setData(res);
    } catch (err) {
      console.error('Failed to load risk data:', err);
    }
    setLoading(false);
  };

  if (loading) return <div className="text-slate-400">Loading...</div>;

  const metrics = data?.metrics || {};
  const drawdowns = data?.drawdowns || [];
  const varData = data?.var_data || {};

  return (
    <div className="space-y-6">
      {/* Risk Metrics Overview */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <RiskCard label="Sharpe Ratio" value={metrics.sharpe?.toFixed(3)} sub="annualized" goodHigher />
        <RiskCard label="Sortino Ratio" value={metrics.sortino?.toFixed(3)} sub="downside risk" goodHigher />
        <RiskCard label="VaR (95%)" value={`${(varData.var_95 * 100)?.toFixed(2)}%`} sub="daily" goodLower />
        <RiskCard label="Max Drawdown" value={`${(drawdowns.max_drawdown * 100)?.toFixed(2)}%`} sub={`from ${drawdowns.drawdown_start}`} goodLower />
        <RiskCard label="Beta" value={metrics.beta?.toFixed(3)} sub="vs market" neutral />
        <RiskCard label="Alpha" value={`${(metrics.alpha * 100)?.toFixed(2)}%`} sub="annualized" goodHigher />
        <RiskCard label="Volatility" value={`${(metrics.volatility * 100)?.toFixed(2)}%`} sub="annualized" goodLower />
        <RiskCard label="Calmar Ratio" value={metrics.calmar?.toFixed(3)} sub="return/drawdown" goodHigher />
      </div>

      {/* Drawdown Chart */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Drawdown History</h3>
        <div className="h-64 flex items-center justify-center text-slate-400">
          Drawdown chart will render here
        </div>
      </div>

      {/* Risk Breakdown by Pie */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Risk by Pie</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="text-left py-2 px-3 text-slate-400 font-medium">Pie</th>
                <th className="text-right py-2 px-3 text-slate-400 font-medium">Volatility</th>
                <th className="text-right py-2 px-3 text-slate-400 font-medium">Sharpe</th>
                <th className="text-right py-2 px-3 text-slate-400 font-medium">Max DD</th>
                <th className="text-right py-2 px-3 text-slate-400 font-medium">VaR (95%)</th>
              </tr>
            </thead>
            <tbody>
              {(data?.pie_risk || []).map((pie) => (
                <tr key={pie.id} className="border-b border-slate-700/50">
                  <td className="py-2 px-3 text-slate-200">{pie.name}</td>
                  <td className="py-2 px-3 text-right text-slate-300">{(pie.volatility * 100).toFixed(2)}%</td>
                  <td className={`py-2 px-3 text-right ${pie.sharpe >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pie.sharpe?.toFixed(3)}
                  </td>
                  <td className="py-2 px-3 text-right text-slate-300">{(pie.max_drawdown * 100).toFixed(2)}%</td>
                  <td className="py-2 px-3 text-right text-slate-300">{(pie.var_95 * 100).toFixed(2)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* VaR Distribution */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">VaR Distribution</h3>
        <div className="grid grid-cols-3 gap-4">
          <div className="p-4 bg-slate-700/30 rounded-lg text-center">
            <p className="text-sm text-slate-400">VaR 95%</p>
            <p className="text-2xl font-bold text-red-400">{(varData.var_95 * 100).toFixed(2)}%</p>
          </div>
          <div className="p-4 bg-slate-700/30 rounded-lg text-center">
            <p className="text-sm text-slate-400">VaR 99%</p>
            <p className="text-2xl font-bold text-red-500">{(varData.var_99 * 100).toFixed(2)}%</p>
          </div>
          <div className="p-4 bg-slate-700/30 rounded-lg text-center">
            <p className="text-sm text-slate-400">CVaR (95%)</p>
            <p className="text-2xl font-bold text-amber-400">{(varData.cvar_95 * 100).toFixed(2)}%</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function RiskCard({ label, value, sub, goodHigher, goodLower, neutral }) {
  let colorClass = 'text-slate-100';
  if (goodHigher && value !== '0') {
    colorClass = parseFloat(value) > 0 ? 'text-emerald-400' : 'text-red-400';
  } else if (goodLower && value !== '0') {
    colorClass = parseFloat(value.replace('%', '')) < 0 ? 'text-emerald-400' : 'text-red-400';
  }
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
      <p className="text-sm text-slate-400">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${colorClass}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  );
}