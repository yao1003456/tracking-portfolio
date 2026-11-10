import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export const login = async (username, password) => {
  const response = await api.post('/auth/login', { username, password });
  return response.data;
};

export const logout = async () => {
  await api.post('/auth/logout');
  localStorage.removeItem('token');
};

export const getAxis = async (params = {}) => {
  const response = await api.get('/axis', { params });
  return response.data;
};

export const getExposures = async (params = {}) => {
  const response = await api.get('/exposures', { params });
  return response.data;
};

export const getCorrelations = async (params = {}) => {
  const response = await api.get('/correlations', { params });
  return response.data;
};

export const getHoldings = async (params = {}) => {
  const response = await api.get('/holdings', { params });
  return response.data;
};

export const getRisk = async (params = {}) => {
  const response = await api.get('/risk', { params });
  return response.data;
};

export const getTransactions = async (params = {}) => {
  const response = await api.get('/transactions', { params });
  return response.data;
};

export const getAttribution = async (params = {}) => {
  const response = await api.get('/attribution', { params });
  return response.data;
};

export const getValuations = async (params = {}) => {
  const response = await api.get('/valuations', { params });
  return response.data;
};

export const getAlerts = async () => {
  const response = await api.get('/alerts');
  return response.data;
};

export const getSettings = async () => {
  const response = await api.get('/settings');
  return response.data;
};

export const updateSettings = async (settings) => {
  const response = await api.put('/settings', settings);
  return response.data;
};

export const importExcel = async (file) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post('/import/excel', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

export const importTrading212 = async (file) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post('/import/trading212', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

export const refreshPrices = async () => {
  const response = await api.post('/prices/refresh');
  return response.data;
};

export default api;