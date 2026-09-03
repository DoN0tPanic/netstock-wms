import { useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { authApi } from '../api';
import {Button, PasswordInput } from '../components/ui';

export function ChangePassword() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const tooShort = next.length > 0 && next.length < 12;
  const doesNotMatch = confirmation.length > 0 && confirmation !== next;
  const valid = current.length > 0 && next.length >= 12 && confirmation === next;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!valid || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      await authApi.changePassword({ current_password: current, new_password: next });
      await queryClient.fetchQuery({ queryKey: ['auth', 'me'], queryFn: authApi.me, staleTime: 0 });
      void navigate('/', { replace: true });
    } catch {
      setError('Impossibile cambiare la password. Verifica quella attuale e i requisiti.');
    } finally {
      setSubmitting(false);
    }
  };

  return <main className="mx-auto max-w-md space-y-4 p-6"><h1 className="text-2xl font-bold">Cambia password</h1><p>Al primo accesso devi scegliere una nuova password di almeno 12 caratteri.</p><form className="space-y-4" onSubmit={(event) => void submit(event)}><PasswordInput label="Password attuale"  autoComplete="current-password" required value={current} onChange={(event) => setCurrent(event.target.value)}/><PasswordInput label="Nuova password"  autoComplete="new-password" required minLength={12} value={next} error={tooShort ? 'La nuova password deve contenere almeno 12 caratteri' : undefined} onChange={(event) => setNext(event.target.value)}/><PasswordInput label="Conferma nuova password"  autoComplete="new-password" required value={confirmation} error={doesNotMatch ? 'Le password non corrispondono' : undefined} onChange={(event) => setConfirmation(event.target.value)}/>{error && <p role="alert" className="text-red-700">{error}</p>}<Button type="submit" disabled={!valid} loading={submitting}>Salva nuova password</Button></form></main>;
}
