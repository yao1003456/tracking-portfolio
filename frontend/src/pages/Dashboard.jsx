import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import Axis from './Axis';
import Exposures from './Exposures';
import Correlation from './Correlation';
import Holdings from './Holdings';
import Risk from './Risk';
import Transactions from './Transactions';
import Attribution from './Attribution';

const TABS = [
  { id: 'axis', label: 'AXIS', icon: '⚡' },
  { id: 'exposures', label: 'EXPOSURES', icon: '📊' },
  { id: 'correlation', label: 'CORRELATION', icon: '🔗' },
  { id: 'holdings', label: 'HOLDINGS', icon: '💼' },
  { id: 'risk', label: 'RISK', icon: '🛡️' },
  { id: 'transactions', label: 'TRANSACTIONS', icon: '📝' },
  { id: 'attribution', label: 'ATTRIBUTION', icon: '📈' },
];

export default function Dashboard() {
  const { signOut } = useAuth();
  const [activeTab, setActiveTab] = useState('axis');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const renderTab = () => {
    switch (activeTab) {
      case 'axis': return <Axis />;
      case 'exposures': return <Exposures />;
      case 'correlation': return <Correlation />;
      case 'holdings': return <Holdings />;
      case 'risk': return <Risk />;
      case 'transactions': return <Transactions />;
      case 'attribution': return <Attribution />;
      default: return <Axis />;
    }
  };

  return (
    <div className="flex h-screen bg-slate-900">
      <aside className={`${sidebarCollapsed ? 'w-16' : 'w-56'} bg-slate-800 border-r border-slate-700 flex flex-col transition-all duration-200`}>
        <div className="p-4 border-b border-slate-700">
          <h1 className={`font-bold text-indigo-400 ${sidebarCollapsed ? 'text-center' : ''}`}>
            {sidebarCollapsed ? 'GDM' : 'Great Dyke Meridian'}
          </h1>
        </div>
        <nav className="flex-1 py-4">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                activeTab === tab.id
                  ? 'bg-indigo-600/20 text-indigo-400 border-r-2 border-indigo-400'
                  : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'
              }`}
              title={tab.label}
            >
              <span className="text-lg">{tab.icon}</span>
              {!sidebarCollapsed && <span className="text-sm font-medium">{tab.label}</span>}
            </button>
          ))}
        </nav>
        <div className="p-4 border-t border-slate-700">
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="w-full py-2 text-slate-400 hover:text-slate-200 text-sm"
          >
            {sidebarCollapsed ? '→' : '← Collapse'}
          </button>
          <button
            onClick={signOut}
            className="w-full mt-2 py-2 text-red-400 hover:text-red-300 text-sm"
          >
            Sign Out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        <header className="sticky top-0 z-10 bg-slate-900/80 backdrop-blur border-b border-slate-700 px-6 py-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-100">
            {TABS.find((t) => t.id === activeTab)?.label}
          </h2>
          <div className="text-sm text-slate-400">
            {new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
          </div>
        </header>
        <div className="p-6">
          {renderTab()}
        </div>
      </main>
    </div>
  );
}