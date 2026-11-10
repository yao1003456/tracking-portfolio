import { createContext, useContext, useState, useEffect } from 'react';
import { login as loginApi, logout as logoutApi } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      setUser({ token });
    }
    setLoading(false);
  }, []);

  const signIn = async (username, password) => {
    const data = await loginApi(username, password);
    localStorage.setItem('token', data.access_token);
    setUser({ token: data.access_token });
  };

  const signOut = async () => {
    await logoutApi();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}