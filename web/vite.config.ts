import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react-swc';

export default defineConfig({
  plugins: [react()],
  // In sviluppo l'API può stare altrove: un'istanza di prova su un altro
  // porto è il solo modo di provare in un browser vero un elenco più lungo
  // di quello che c'è in produzione, senza scriverci dentro dati finti.
  server: { proxy: { '/api': process.env.NETSTOCK_API ?? 'http://localhost:8000' } },
  test: { environment: 'happy-dom', setupFiles: './src/test/setup.ts', globals: true },
});
