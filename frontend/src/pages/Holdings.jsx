import { useState, useEffect } from 'react';
import { getHoldings } from '../api';

export default function Holdings() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState('value');
  const [sortDir, setSortDir] = useState('desc');

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await getHoldings();
      setData(res);
    } catch (err) {
      console.error('Failed to load holdings:', err);
    }
    setLoading(false);
  };

  if (loading) return <div className="text-slate-400">Loading...</div>;

  const positions = data?.positions || [];
  const filtered = positions.filter((p) =>
    p.ticker?.toLowerCase().includes(search.toLowerCase()) ||
    p.name?.toLowerCase().includes(search.toLowerCase())
  );

  const sorted = [...filtered].sort((a, b) => {
    let va = a[sortBy] || 0;
    let vb = b[sortBy] || 0;
    return sortDir === 'desc' ? vb - va : va - vb;
  });

  return (
    <div className="space-y-6">
      {/* Search & Sort */}
      <div className="flex gap-3">
        <input
          type="text"
          placeholder="Search ticker or name..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        />
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100"
        >
          <option value="value">Value</option>
          <option value="weight">Weight</option>
          <option value="return">Return</option>
          <option value="cost_basis">Cost Basis</option>
        </select>
        <button
          onClick={() => setSortDir(sortDir === 'desc' ? 'asc' : 'desc')}
          className="px-4 py-2 bg-slate-700 border border-slate-600 rounded-lg text-slate-300 hover:bg-slate-600"
        >
          {sortDir === 'desc' ? '↓' : '↑'}
        </button>
      </div>

      {/* Holdings Table */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-700/50 border-b border-slate-700">
                <th className="text-left py-3 px-4 text-slate-400 font-medium">Ticker</th>
                <th className="text-left py-3 px-4 text-slate-400 font-medium">Name</th>
                <th className="text-right py-3 px-4 text-slate-400 font-medium">Qty</th>
                <th className="text-right py-3 px-4 text-slate-400 font-medium">Price</th>
                <th className="text-right py-3 px-4 text-slate-400 font-medium">Value</th>
                <th className="text-right py-3 px-4 text-slate-400 font-medium">Weight</th>
                <th className="text-right py-3 px-4 text-slate-400 font-medium">Cost Basis</th>
                <th className="text-right py-3 px-4 text-slate-400 font-medium">Gain/Loss</th>
                <th className="text-right py-3 px-4 text-slate-400 font-medium">Return</th>
                <th className="text-center py-3 px-4 text-slate-400 font-medium">Pie</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((pos) => (
                <tr key={pos.id} className="border-b border-slate-700/50 hover:bg-slate-700/20">
                  <td className="py-3 px-4 font-mono text-indigo-400">{pos.ticker}</td>
                  <td className="py-3 px-4 text-slate-300">{pos.name}</td>
                  <td className="py-3 px-4 text-right text-slate-300">{pos.quantity?.toLocaleString()}</td>
                  <td className="py-3 px-4 text-right text-slate-300">£{pos.price?.toFixed(4)}</td>
                  <td className="py-3 px-4 text-right font-medium text-slate-100">£{pos.value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                  <td className="py-3 px-4 text-right">
                    <span className="px-2 py-0.5 bg-slate-600/50 rounded text-xs">{pos.weight?.toFixed(2)}%</span>
                  </td>
                  <td className="py-3 px-4 text-right text-slate-300">£{pos.cost_basis?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                  <td className={`py-3 px-4 text-right ${pos.unrealized_gain >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    £{pos.unrealized_gain?.toLocaleString(undefined, { minimumFractionDigits: 2, signDisplay: 'exceptZero' })}
                  </td>
                  <td className={`py-3 px-4 text-right ${pos.total_return_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pos.total_return_pct?.toFixed(2)}%
                  </td>
                  <td className="py-3 px-4 text-center">
                    <span className="px-2 py-0.5 bg-indigo-500/20 text-indigo-300 rounded text-xs">{pos.pie_name || '-'}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard label="Total Positions" value={positions.length} />
        <StatCard label="Total Value" value={`£${data?.total_value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}`} />
        <StatCard label="Total Gain/Loss" value={`£${data?.total_gain_loss?.toLocaleString(undefined, { minimumFractionDigits: 2, signDisplay: 'exceptZero' })}`} />
        <StatCard label="Avg Return" value={`${data?.avg_return_pct?.toFixed(2)}%`} />
      </div>
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
      <p className="text-sm text-slate-400">{label}</p>
      <p className="text-xl font-bold text-slate-100 mt-1">{value}</p>
    </div>
  );
}