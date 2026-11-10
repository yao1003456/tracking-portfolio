import { useState, useEffect } from 'react';
import { getAxis, getValuations, getAlerts } from '../api';

const RAG_COLORS = {
  green: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  amber: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  red: 'bg-red-500/20 text-red-400 border-red-500/30',
};

export default function Axis() {
  const [data, setData] = useState(null);
  const [valuations, setValuations] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dateRange, setDateRange] = useState('YTD');

  const loadData = async () => {
    setLoading(true);
    try {
      const [axis, vals, alertsData] = await Promise.all([
        getAxis({ period: dateRange }),
        getValuations({ limit: 30 }),
        getAlerts(),
      ]);
      setData(axis);
      setValuations(vals);
      setAlerts(alertsData);
    } catch (err) {
      console.error('Failed to load AXIS data:', err);
    }
    setLoading(false);
  };

  useEffect(() => { loadData(); }, [dateRange]);

  if (loading) return <div className="text-slate-400">Loading...</div>;

  const summary = data?.summary || {};
  const pies = data?.pies || [];

  return (
    <div className="space-y-6">
      {/* Key Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard title="Total Portfolio Value" value={`£${summary.total_value?.toLocaleString(undefined, { minimumFractionDigits: 2 }) || '0.00'}`} change={summary.total_return_pct} />
        <MetricCard title="Daily P&L" value={`£${summary.daily_pnl?.toLocaleString() || '0'}`} change={summary.daily_return_pct} isCurrency />
        <MetricCard title="YTD Return" value={`${summary.ytd_return_pct?.toFixed(2) || '0'}%`} isPercent />
        <MetricCard title="Active Alerts" value={alerts.length} isAlert />
      </div>

      {/* Pie Allocations */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Portfolio Allocations</h3>
        <div className="space-y-3">
          {pies.map((pie) => (
            <div key={pie.id} className="flex items-center justify-between p-3 bg-slate-700/30 rounded-lg">
              <div className="flex items-center gap-3">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: pie.color || '#6366f1' }} />
                <span className="text-slate-200 font-medium">{pie.name}</span>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-slate-300">£{pie.value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${RAG_COLORS[pie.rag || 'green']}`}>
                  {pie.rag?.toUpperCase() || 'OK'}
                </span>
                <span className="text-slate-400 w-16 text-right">{pie.percentage?.toFixed(1)}%</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Valuation Chart */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Portfolio Value History</h3>
        <div className="h-64 flex items-center justify-center text-slate-400">
          Chart component will render here with valuation data
        </div>
      </div>

      {/* Alerts */}
      {alerts.length > 0 && (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
          <h3 className="text-lg font-semibold text-slate-100 mb-4">Active Alerts</h3>
          <div className="space-y-2">
            {alerts.map((alert) => (
              <div key={alert.id} className="flex items-center gap-3 p-3 bg-slate-700/30 rounded-lg">
                <span className={`w-2 h-2 rounded-full ${alert.severity === 'high' ? 'bg-red-500' : alert.severity === 'medium' ? 'bg-amber-500' : 'bg-blue-500'}`} />
                <span className="text-slate-200 text-sm">{alert.message}</span>
                <span className="text-slate-500 text-xs ml-auto">{new Date(alert.created_at).toLocaleDateString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCard({ title, value, change, isPercent, isCurrency, isAlert }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-5">
      <p className="text-sm text-slate-400 mb-1">{title}</p>
      <p className={`text-2xl font-bold ${isAlert ? 'text-indigo-400' : 'text-slate-100'}`}>
        {value}
      </p>
      {change !== undefined && change !== null && !isAlert && (
        <p className={`text-sm mt-1 ${change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          {change >= 0 ? '↑' : '↓'} {Math.abs(change).toFixed(2)}%
        </p>
      )}
    </div>
  );
}