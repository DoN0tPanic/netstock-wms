/** @type {import('tailwindcss').Config} */

// La scala `blue` viene ridefinita invece di introdurre un nome nuovo: nel
// codice ci sono oltre cento utilità `blue-*`, e cambiare qui il significato
// del nome le sposta tutte insieme, senza toccarne una.
//
// Navy istituzionale al posto del blu acceso di serie. Il passo 600 — quello
// dei pulsanti — dà 8,63:1 contro il testo bianco, dove il precedente si
// fermava a 5,17:1.
//
// `chart` è deliberatamente **un altro colore**, non il 600 della scala: i due
// fanno lavori diversi. Un pulsante vuole contrasto col testo che ci sta
// sopra, una barra di grafico vuole abbastanza croma da non leggersi grigia su
// una scala di valori. Il navy dell'interfaccia, misurato come colore di
// grafico, non supera la soglia di croma; questo sì.
const navy = {
  50:  '#f1f5fa',
  100: '#dde8f3',
  200: '#bed3e8',
  300: '#92b4d6',
  400: '#5e8ec0',
  500: '#3a70a8',
  600: '#1d4e7c',
  700: '#174065',
  800: '#143451',
  900: '#112a41',
};

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        blue: navy,
        brand: navy,
        chart: '#2a6fb8',
      },
    },
  },
  plugins: [],
};
