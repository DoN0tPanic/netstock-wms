import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { PasswordInput } from './index';

const campo = () => screen.getByLabelText<HTMLInputElement>('Password');

describe('PasswordInput', () => {
  it('parte nascosto', () => {
    render(<PasswordInput label="Password"/>);
    expect(campo()).toHaveAttribute('type', 'password');
  });

  it('mostra e rinasconde quello che si è scritto', async () => {
    // È il motivo per cui esiste: sul telefono la barra dei suggerimenti
    // aggiunge spazi e il maiuscolo automatico cambia la prima lettera, e con
    // i pallini al posto dei caratteri non c'è modo di accorgersene.
    render(<PasswordInput label="Password"/>);
    await userEvent.type(campo(), 'Prova!2026');

    await userEvent.click(screen.getByRole('button', { name: 'Mostra la password' }));
    expect(campo()).toHaveAttribute('type', 'text');
    expect(campo()).toHaveValue('Prova!2026');

    await userEvent.click(screen.getByRole('button', { name: 'Nascondi la password' }));
    expect(campo()).toHaveAttribute('type', 'password');
  });

  it('torna nascosto quando si lascia il campo', async () => {
    render(<><PasswordInput label="Password"/><button type="button">altrove</button></>);
    await userEvent.click(screen.getByRole('button', { name: 'Mostra la password' }));
    await userEvent.click(campo());
    await userEvent.click(screen.getByRole('button', { name: 'altrove' }));
    expect(campo()).toHaveAttribute('type', 'password');
  });

  it('non invia il modulo che lo contiene', async () => {
    // Un `button` senza type esplicito dentro un form vale come submit: qui
    // significherebbe tentare l'accesso ogni volta che si sbircia la password.
    let inviato = false;
    render(<form onSubmit={() => { inviato = true; }}><PasswordInput label="Password"/></form>);
    await userEvent.click(screen.getByRole('button', { name: 'Mostra la password' }));
    expect(inviato).toBe(false);
  });
});
