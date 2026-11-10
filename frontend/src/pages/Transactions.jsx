import { useState, useEffect } from 'react';
import { getTransactions } from '../api';

export default function Transactions() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState('all');
  const [page, setPage] = useState(1);
  const pageSize = 25;

  useEffect(() => { loadData(); }, [filterType, page]);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await getTransactions({ type: filterType, page, limit: pageSize });
      setData(res);
    } catch (err) {
      console.error('Failed to load transactions:', err);
    }
    setLoading(false);
  };

  if (loading) return <div className="text-slate-400">Loading...</div>;

  const transactions = data?.transactions || [];
  const total = data?.total || 0;

  const filtered = transactions.filter((t) => {
    if (search && !t.ticker?.toLowerCase().includes(search.toLowerCase()) && !t.type?.toLowerCase().includes(search.toLowerCase())) return false;
    if (filterType !== 'all' && t.type !== filterType) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Search transactions..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 min-w-48 px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 focus:ring-2 focus:ring-indigo-500"
        />
        {['all', 'buy', 'sell', 'dividend', 'fee'].map((type) => (
          <button
            key={type}
            onClick={() => setFilterType(type)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              filterType === type ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            {type.charAt(0).toUpperCase() + type.slice(1)}
          </button>
        ))}
      </div>

      {/* Summary */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard label="Total Transactions" value={total} />
        <StatCard label="Buys" value={data?.buy_count || 0} color="text-emerald-400" />
        <StatCard label="Sells" value={data?.sell_count || 0} color="text-red-400" />
        <StatCard label="Total Fees" value={`£${(data?.total_fees || 0).toFixed(2)}`} color="text-amber-400" />
      </div>

      {/* Tax Summary */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Tax Year Summary</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 bg-slate-700/30 rounded-lg">
            <p className="text-sm text-slate-400">Realized Gains</p>
            <p className="text-2xl font-bold text-emerald-400">£{(data?.realized_gains || 0).toFixed(2)}</p>
          </div>
          <div className="p-4 bg-slate-700/30 rounded-lg">
            <p className="text-sm text-slate-400">Realized Losses</p>
            <p className="text-2xl font-bold text-red-400">£{(data?.realized_losses || 0).toFixed(2)}</p>
          </div>
          <div className="p-4 bg-slate-700/30 rounded-lg">
            <p className="text-sm text-slate-400">Net Gain</p>
            <p className={`text-2xl font-bold ${(data?.net_gain || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              £{(data?.net_gain || 0).toFixed(2)}
            </p>
          </div>
        </div>
      </div>

      {/* Transactions Table */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-700/50 border-b border-slate-700">
                <th className="text-left py-3 px-4 text-slate-400 font-medium">Date</th>
                <th className="text-left py-3 px-4 text-slate-400 font-medium">Type</th>
                <th className="text-left py-3 px-4 text-slate-400 font-medium">Ticker</th>
                <th className="text-right py-3 px-4 text-slate-400 font-medium">Qty</th>
                <th className="text-right py-3 px-4 text-slate-400 font-medium">Price</th>
                <th className="text-right py-3 px-4 text-slate-400 font-medium">Amount</th>
                <th className="text-right py-3 px-4 text-slate-400 font-medium">Fee</th>
                <th className="text-center py-3 px-4 text-slate-400 font-medium">Pie</th>
                <th className="text-right py-3 px-4 text-slate-400 font-medium">Gain/Loss</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((tx) => (
                <tr key={tx.id} className="border-b border-slate-700/50 hover:bg-slate-700/20">
                  <td className="py-3 px-4 text-slate-300">{new Date(tx.date).toLocaleDateString('en-GB')}</td>
                  <td className="py-3 px-4">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      tx.type === 'buy' ? 'bg-emerald-500/20 text-emerald-400' :
                      tx.type === 'sell' ? 'bg-red-500/20 text-red-400' :
                      tx.type === 'dividend' ? 'bg-blue-500/20 text-blue-400' :
                      'bg-amber-500/20 text-amber-400'
                    }`}>
                      {tx.type?.toUpperCase()}
                    </span>
                  </td>
                  <td className="py-3 px-4 font-mono text-indigo-400">{tx.ticker}</td>
                  <td className="py-3 px-4 text-right text-slate-300">{tx.quantity?.toLocaleString()}</td>
                  <td className="py-3 px-4 text-right text-slate-300">£{tx.price?.toFixed(4)}</td>
                  <td className="py-3 px-4 text-right text-slate-300">£{tx.amount?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                  <td className="py-3 px-4 text-right text-slate-300">£{tx.fee?.toFixed(2)}</td>
                  <td className="py-3 px-4 text-center">
                    <span className="px-2 py-0.5 bg-indigo-500/20 text-indigo-300 rounded text-xs">{tx.pie_name || '-'}</span>
                  </td>
                  <td className={`py-3 px-4 text-right ${(tx.gain_loss || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    £{(tx.gain_loss || 0).toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      {total > pageSize && (
        <div className="flex items-center justify-center gap-2">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            className="px-4 py-2 bg-slate-700 border border-slate-600 rounded-lg text-slate-300 disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-slate-400">Page {page}</span>
          <button
            onClick={() => setPage(page + 1)}
            disabled={page * pageSize >= total}
            className="px-4 py-2 bg-slate-700 border border-slate-600 rounded-lg text-slate-300 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
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