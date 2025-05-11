import axios, { AxiosInstance, InternalAxiosRequestConfig, AxiosError, AxiosResponse } from 'axios';
import { destroyCookie, parseCookies, setCookie } from 'nookies';

// API configuration
const API_CONFIG = {
  BASE_URL: 'http://localhost:8000',
  AUTH_APP: '/auth',
  ROUTES: {
    TOKEN_REFRESH: '/token/refresh/',
    PROFILE: '/profile',
  },
  COOKIE_OPTIONS: {
    MAX_AGE: 30 * 24 * 60 * 60, // 30 days
    PATH: '/',
    SAME_SITE: 'lax' as const,
    SECURE: false, // Set to true in production with HTTPS
    HTTP_ONLY: false, // Client-side JS needs access
  }
};

// Ensure API_URL has the correct protocol
let API_URL = API_CONFIG.BASE_URL;

// If we're in the browser and the page is using HTTPS, ensure API uses HTTPS too
// unless it's explicitly set to localhost or 127.0.0.1
if (typeof window !== 'undefined' && window.location.protocol === 'https:') {
    if (!API_URL.includes('localhost') && !API_URL.includes('127.0.0.1')) {
        API_URL = API_URL.replace('http://', 'https://');
    }
}

const api: AxiosInstance = axios.create({
    baseURL: API_URL,
    withCredentials: true,
    headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
    },
});

// Request interceptor to add auth token
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    const cookies = parseCookies();
    const token = cookies.access_token;
    
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    
    return config;
});

// Response interceptor to handle token refresh
api.interceptors.response.use(
    (response: AxiosResponse) => response,
    async (error: AxiosError) => {
        const { AUTH_APP, ROUTES } = API_CONFIG;
        const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };
        
        // Handle 401 Unauthorized errors
        if (error.response?.status === 401) {
            // If the token refresh endpoint itself returns 401, logout
            if (originalRequest.url?.endsWith(`${AUTH_APP}${ROUTES.TOKEN_REFRESH}`)) {
                clearAuthCookies();
                redirectToLogin(originalRequest);
                return Promise.reject(error);
            }

            // Try to refresh the token once
            if (!originalRequest._retry) {
                originalRequest._retry = true;
                try {
                    return await refreshTokenAndRetry(originalRequest);
                } catch (refreshError) {
                    clearAuthCookies();
                    redirectToLogin(originalRequest);
                    return Promise.reject(refreshError);
                }
            }
        }
        
        return Promise.reject(error);
    }
);

// Helper functions
function clearAuthCookies(): void {
    setAuthToken(null);
    destroyCookie(null, 'access_token', { path: API_CONFIG.COOKIE_OPTIONS.PATH });
    destroyCookie(null, 'refresh_token', { path: API_CONFIG.COOKIE_OPTIONS.PATH });
}

function redirectToLogin(request: InternalAxiosRequestConfig): void {
    const { AUTH_APP, ROUTES } = API_CONFIG;
    
    // Only redirect if in browser context and not a silent profile check
    if (
        typeof window !== 'undefined' &&
        request.url && 
        !request.url.includes(`${AUTH_APP}${ROUTES.PROFILE}`)
    ) {
        window.location.href = '/login';
    }
}

async function refreshTokenAndRetry(originalRequest: InternalAxiosRequestConfig): Promise<AxiosResponse> {
    const { AUTH_APP, ROUTES } = API_CONFIG;
    const cookies = parseCookies();
    const refreshToken = cookies.refresh_token;
    
    if (!refreshToken) {
        throw new Error('No refresh token available');
    }
    
    const response = await api.post(`${AUTH_APP}${ROUTES.TOKEN_REFRESH}`, {
        refresh: refreshToken,
    });
    
    const { access } = response.data;
    setAuthToken(access);
    
    originalRequest.headers.Authorization = `Bearer ${access}`;
    
    return api(originalRequest);
}

export const setAuthToken = (token: string | null, ctx: any = null): void => {
    const { COOKIE_OPTIONS } = API_CONFIG;
    
    if (token) {
        api.defaults.headers.common['Authorization'] = `Bearer ${token}`;
        setCookie(ctx, 'access_token', token, {
            maxAge: COOKIE_OPTIONS.MAX_AGE,
            path: COOKIE_OPTIONS.PATH,
            sameSite: COOKIE_OPTIONS.SAME_SITE,
            secure: COOKIE_OPTIONS.SECURE,
            httpOnly: COOKIE_OPTIONS.HTTP_ONLY,
        });
    } else {
        delete api.defaults.headers.common['Authorization'];
        destroyCookie(ctx, 'access_token');
    }
};

// Generic response type for list endpoints
export interface ListResponse<T> {
    objects: T[];
    total_count: number;
    num_pages: number;
    current_page: number;
}

// Generic API class with better typing
export class GenericApi<ReadType, WriteType = ReadType> {
    private endpoint: string;

    constructor(endpoint: string) {
        if (!endpoint) {
            throw new Error('Endpoint is required for GenericApi');
        }
        this.endpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
    }

    async get(id: number | string): Promise<ReadType> {
        try {
            const response = await api.get(`${this.endpoint}/${id}/`);
            return response.data;
        } catch (error) {
            console.error(`Error in ${this.endpoint}-get:`, error);
            throw error;
        }
    }

    async filter(filters?: Record<string, any>): Promise<ListResponse<ReadType>> {
        try {
            const response = await api.get(`${this.endpoint}/`, {
                params: filters,
            });
            return response.data;
        } catch (error) {
            console.error(`Error in ${this.endpoint}-filter:`, error);
            throw error;
        }
    }

    async create(data: WriteType): Promise<ReadType> {
        try {
            const response = await api.post(`${this.endpoint}/`, data);
            return response.data;
        } catch (error) {
            console.error(`Error in ${this.endpoint}-create:`, error);
            throw error;
        }
    }

    async update(id: number | string, data: Partial<WriteType>): Promise<ReadType> {
        try {
            const response = await api.put(`${this.endpoint}/${id}/`, data);
            return response.data;
        } catch (error) {
            console.error(`Error in ${this.endpoint}-update:`, error);
            throw error;
        }
    }

    async delete(id: number | string): Promise<void> {
        try {
            await api.delete(`${this.endpoint}/${id}/`);
        } catch (error) {
            console.error(`Error in ${this.endpoint}-delete:`, error);
            throw error;
        }
    }
}

export default api;
