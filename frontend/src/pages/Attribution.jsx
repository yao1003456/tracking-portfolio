import { useState, useEffect } from 'react';
import { getAttribution } from '../api';

export default function Attribution() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState('YTD');

  useEffect(() => { loadData(); }, [period]);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await getAttribution({ period });
      setData(res);
    } catch (err) {
      console.error('Failed to load attribution:', err);
    }
    setLoading(false);
  };

  if (loading) return <div className="text-slate-400">Loading...</div>;

  const pieAttribution = data?.pie_attribution || [];
  const sectorAttribution = data?.sector_attribution || [];
  const holdingAttribution = data?.holding_attribution || [];
  const benchmarkComparison = data?.benchmark_comparison || {};

  return (
    <div className="space-y-6">
      {/* Period Selector */}
      <div className="flex gap-2">
        {['1M', '3M', '6M', 'YTD', '1Y', 'ALL'].map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              period === p ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      {/* Summary */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard label="Portfolio Return" value={`${(benchmarkComparison.portfolio_return || 0).toFixed(2)}%`} color="text-slate-100" />
        <StatCard label="Benchmark Return" value={`${(benchmarkComparison.benchmark_return || 0).toFixed(2)}%`} color="text-slate-400" />
        <StatCard label="Alpha" value={`${(benchmarkComparison.alpha || 0).toFixed(2)}%`} color={benchmarkComparison.alpha >= 0 ? 'text-emerald-400' : 'text-red-400'} />
        <StatCard label="Tracking Error" value={`${(benchmarkComparison.tracking_error || 0).toFixed(2)}%`} color="text-amber-400" />
      </div>

      {/* Pie Attribution */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Return by Pie</h3>
        <div className="space-y-3">
          {pieAttribution.map((pie) => (
            <div key={pie.id} className="flex items-center gap-4">
              <span className="text-slate-300 w-32 truncate">{pie.name}</span>
              <div className="flex-1 bg-slate-700/50 rounded-full h-6 overflow-hidden relative">
                <div
                  className={`h-full rounded-full transition-all ${pie.return >= 0 ? 'bg-emerald-500' : 'bg-red-500'}`}
                  style={{ width: `${Math.min(Math.abs(pie.return) * 10, 100)}%` }}
                />
                <span className="absolute inset-0 flex items-center justify-center text-xs text-white font-medium">
                  {pie.return >= 0 ? '+' : ''}{pie.return?.toFixed(2)}%
                </span>
              </div>
              <span className="text-slate-400 w-20 text-right">
                Contrib: {pie.contribution?.toFixed(2)}%
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Sector Attribution */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Return by Sector</h3>
        <div className="space-y-3">
          {sectorAttribution.map((sec) => (
            <div key={sec.sector} className="flex items-center gap-4">
              <span className="text-slate-300 w-32 truncate">{sec.sector}</span>
              <div className="flex-1 bg-slate-700/50 rounded-full h-6 overflow-hidden relative">
                <div
                  className={`h-full rounded-full transition-all ${sec.return >= 0 ? 'bg-emerald-500' : 'bg-red-500'}`}
                  style={{ width: `${Math.min(Math.abs(sec.return) * 10, 100)}%` }}
                />
                <span className="absolute inset-0 flex items-center justify-center text-xs text-white font-medium">
                  {sec.return >= 0 ? '+' : ''}{sec.return?.toFixed(2)}%
                </span>
              </div>
              <span className="text-slate-400 w-20 text-right">
                {sec.holding_count} holdings
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Top Contributors */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Top Holdings Contribution</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="text-left py-2 px-3 text-slate-400 font-medium">#</th>
                <th className="text-left py-2 px-3 text-slate-400 font-medium">Holding</th>
                <th className="text-right py-2 px-3 text-slate-400 font-medium">Weight</th>
                <th className="text-right py-2 px-3 text-slate-400 font-medium">Return</th>
                <th className="text-right py-2 px-3 text-slate-400 font-medium">Contribution</th>
                <th className="text-right py-2 px-3 text-slate-400 font-medium">vs Benchmark</th>
              </tr>
            </thead>
            <tbody>
              {holdingAttribution.slice(0, 10).map((h, i) => (
                <tr key={h.id} className="border-b border-slate-700/50">
                  <td className="py-2 px-3 text-slate-500">{i + 1}</td>
                  <td className="py-2 px-3 text-slate-200">{h.ticker} - {h.name}</td>
                  <td className="py-2 px-3 text-right text-slate-300">{h.weight?.toFixed(2)}%</td>
                  <td className={`py-2 px-3 text-right ${h.return >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {h.return?.toFixed(2)}%
                  </td>
                  <td className={`py-2 px-3 text-right ${h.contribution >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {h.contribution?.toFixed(2)}%
                  </td>
                  <td className={`py-2 px-3 text-right ${h.active_return >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {h.active_return?.toFixed(2)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Brinson Attribution */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Brinson-Fachler Attribution</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 bg-slate-700/30 rounded-lg">
            <p className="text-sm text-slate-400">Allocation Effect</p>
            <p className={`text-2xl font-bold ${(data?.allocation_effect || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {(data?.allocation_effect || 0).toFixed(2)}%
            </p>
          </div>
          <div className="p-4 bg-slate-700/30 rounded-lg">
            <p className="text-sm text-slate-400">Selection Effect</p>
            <p className={`text-2xl font-bold ${(data?.selection_effect || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {(data?.selection_effect || 0).toFixed(2)}%
            </p>
          </div>
          <div className="p-4 bg-slate-700/30 rounded-lg">
            <p className="text-sm text-slate-400">Interaction Effect</p>
            <p className={`text-2xl font-bold ${(data?.interaction_effect || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {(data?.interaction_effect || 0).toFixed(2)}%
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, color = 'text-slate-100' }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
      <p className="text-sm text-slate-400">{label}</p>
      <p className={`text-xl font-bold mt-1 ${color}`}>{value}</p>
    </div>
  );
}