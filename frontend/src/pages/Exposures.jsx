import { useState, useEffect } from 'react';
import { getExposures } from '../api';

export default function Exposures() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await getExposures();
      setData(res);
    } catch (err) {
      console.error('Failed to load exposures:', err);
    }
    setLoading(false);
  };

  if (loading) return <div className="text-slate-400">Loading...</div>;

  const currencyExp = data?.currency_exposure || [];
  const sectorExp = data?.sector_exposure || [];
  const pieExp = data?.pie_exposure || [];
  const concentration = data?.concentration || {};

  return (
    <div className="space-y-6">
      {/* Currency Exposure */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Currency Exposure</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          {currencyExp.map((cur) => (
            <div key={cur.currency} className="p-4 bg-slate-700/30 rounded-lg text-center">
              <div className="text-2xl mb-1">{cur.flag || cur.currency}</div>
              <div className="text-sm text-slate-300 font-medium">{cur.currency}</div>
              <div className="text-lg font-bold text-slate-100 mt-1">{cur.percentage?.toFixed(1)}%</div>
              <div className="text-xs text-slate-400">£{cur.value?.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Sector Exposure */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Sector Exposure</h3>
        <div className="space-y-2">
          {sectorExp.map((sec) => (
            <div key={sec.sector} className="flex items-center gap-4">
              <span className="text-slate-300 w-32">{sec.sector}</span>
              <div className="flex-1 bg-slate-700/50 rounded-full h-4 overflow-hidden">
                <div
                  className="h-full bg-indigo-500 rounded-full transition-all"
                  style={{ width: `${sec.percentage}%` }}
                />
              </div>
              <span className="text-slate-300 w-16 text-right">{sec.percentage?.toFixed(1)}%</span>
              <span className="text-slate-400 w-24 text-right">£{sec.value?.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Concentration */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Concentration Metrics</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 bg-slate-700/30 rounded-lg">
            <p className="text-sm text-slate-400">HHI Index</p>
            <p className="text-2xl font-bold text-slate-100">{concentration.hhi?.toFixed(2) || '0'}</p>
            <p className="text-xs text-slate-500 mt-1">0-10000 scale</p>
          </div>
          <div className="p-4 bg-slate-700/30 rounded-lg">
            <p className="text-sm text-slate-400">Top 5 Holdings</p>
            <p className="text-2xl font-bold text-slate-100">{concentration.top5_pct?.toFixed(1) || '0'}%</p>
            <p className="text-xs text-slate-500 mt-1">of total portfolio</p>
          </div>
          <div className="p-4 bg-slate-700/30 rounded-lg">
            <p className="text-sm text-slate-400">Effective N</p>
            <p className="text-2xl font-bold text-slate-100">{concentration.effective_n?.toFixed(1) || '0'}</p>
            <p className="text-xs text-slate-500 mt-1">diversified positions</p>
          </div>
        </div>
      </div>

      {/* Pie Breakdown */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Pie Breakdown</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="text-left py-2 px-3 text-slate-400 font-medium">Pie</th>
                <th className="text-right py-2 px-3 text-slate-400 font-medium">Value</th>
                <th className="text-right py-2 px-3 text-slate-400 font-medium">Allocation</th>
                <th className="text-right py-2 px-3 text-slate-400 font-medium">Positions</th>
              </tr>
            </thead>
            <tbody>
              {pieExp.map((pie) => (
                <tr key={pie.id} className="border-b border-slate-700/50">
                  <td className="py-2 px-3 text-slate-200">{pie.name}</td>
                  <td className="py-2 px-3 text-right text-slate-300">£{pie.value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                  <td className="py-2 px-3 text-right text-slate-300">{pie.percentage?.toFixed(1)}%</td>
                  <td className="py-2 px-3 text-right text-slate-300">{pie.position_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}