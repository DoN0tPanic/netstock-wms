import { createContext, useContext, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { authApi } from '../api';
import { ApiError } from '../api/client';
// `setQueryData(chiave, undefined)` non svuota niente: in TanStack Query un
// valore `undefined` significa «non cambiare nulla». L'uscita chiudeva la
// sessione sul server — le chiamate successive rispondevano 401 — mentre
// l'interfaccia restava dov'era, con l'utente ancora scritto in alto a
// destra. `removeQueries()` senza filtro toglie anche il resto della cache,
// che è quello che serve quando sullo stesso computer entra un'altra
// persona: il magazzino di prima non deve restarle sotto gli occhi.
import type { AuthMe, LoginRequest } from '../types/api';
const AuthContext = createContext<{ session?: AuthMe; loading: boolean; login: (body: LoginRequest) => Promise<AuthMe>; logout: () => Promise<void> } | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) { const queryClient = useQueryClient(); const query = useQuery({ queryKey: ['auth', 'me'], queryFn: authApi.me, retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 1, staleTime: 60_000 }); const loginMutation = useMutation({ mutationFn: authApi.login, onSuccess: (data) => queryClient.setQueryData(['auth', 'me'], data) }); const logoutMutation = useMutation({ mutationFn: authApi.logout, onSuccess: () => queryClient.removeQueries() }); return <AuthContext.Provider value={{ session: query.data, loading: query.isLoading, login: loginMutation.mutateAsync, logout: logoutMutation.mutateAsync }}>{children}</AuthContext.Provider>; }
export const useAuth = () => { const value = useContext(AuthContext); if (!value) throw new Error('useAuth must be used inside AuthProvider'); return value; };
