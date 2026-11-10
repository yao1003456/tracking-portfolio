import { useState, useEffect } from 'react';
import { getCorrelations } from '../api';

export default function Correlation() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState('stock');

  useEffect(() => { loadData(); }, [view]);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await getCorrelations({ type: view });
      setData(res);
    } catch (err) {
      console.error('Failed to load correlations:', err);
    }
    setLoading(false);
  };

  if (loading) return <div className="text-slate-400">Loading...</div>;

  const matrix = data?.stock_correlation || [];
  const sectorMatrix = data?.sector_correlation || [];
  const heatmap = data?.heatmap || [];

  return (
    <div className="space-y-6">
      {/* View Toggle */}
      <div className="flex gap-2">
        {['stock', 'sector', 'benchmark'].map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              view === v ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            {v.charAt(0).toUpperCase() + v.slice(1)}
          </button>
        ))}
      </div>

      {/* Correlation Heatmap */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Correlation Heatmap</h3>
        <div className="overflow-x-auto">
          {matrix.length > 0 ? (
            <table className="text-xs">
              <thead>
                <tr>
                  <th className="p-2"></th>
                  {matrix[0]?.labels.map((label, i) => (
                    <th key={i} className="p-1 text-slate-400 rotate-45 text-left">{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.map((row, ri) => (
                  <tr key={ri}>
                    <td className="p-2 text-slate-400 font-medium">{row.label}</td>
                    {row.values.map((val, ci) => (
                      <td key={ci} className="p-1 text-center">
                        <div
                          className="w-8 h-8 rounded flex items-center justify-center text-xs font-medium"
                          style={{
                            backgroundColor: corrColor(val),
                            color: Math.abs(val) > 0.5 ? 'white' : 'rgba(255,255,255,0.7)'
                          }}
                        >
                          {val.toFixed(2)}
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="h-64 flex items-center justify-center text-slate-400">
              No correlation data available
            </div>
          )}
        </div>
      </div>

      {/* Concentration of Risk */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Risk Concentration</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 bg-slate-700/30 rounded-lg">
            <p className="text-sm text-slate-400">Avg Pairwise Correlation</p>
            <p className="text-2xl font-bold text-slate-100">{data?.avg_correlation?.toFixed(3) || '0'}</p>
          </div>
          <div className="p-4 bg-slate-700/30 rounded-lg">
            <p className="text-sm text-slate-400">Max Correlation</p>
            <p className="text-2xl font-bold text-slate-100">{data?.max_correlation?.toFixed(3) || '0'}</p>
          </div>
          <div className="p-4 bg-slate-700/30 rounded-lg">
            <p className="text-sm text-slate-400">Diversification Ratio</p>
            <p className="text-2xl font-bold text-slate-100">{data?.diversification_ratio?.toFixed(2) || '0'}</p>
          </div>
        </div>
      </div>

      {/* Hierarchical Clustering */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Cluster Analysis</h3>
        <div className="h-64 flex items-center justify-center text-slate-400">
          Dendrogram visualization will render here
        </div>
      </div>
    </div>
  );
}

function corrColor(val) {
  if (val > 0.7) return 'rgba(16, 185, 129, 0.8)';
  if (val > 0.3) return 'rgba(99, 102, 241, 0.6)';
  if (val > -0.3) return 'rgba(100, 116, 139, 0.4)';
  if (val > -0.7) return 'rgba(245, 158, 11, 0.6)';
  return 'rgba(239, 68, 68, 0.8)';
}