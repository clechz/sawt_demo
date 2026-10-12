import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import {fileURLToPath, URL} from 'node:url';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {'process.env.NODE_ENV': JSON.stringify('production')},
  resolve: {alias: {'@': fileURLToPath(new URL('.', import.meta.url))}},
  build: {
    outDir: '../static/v2/ui', emptyOutDir: true,
    lib: {entry: 'src/orb.tsx', formats: ['es'], fileName: () => 'orb.js', cssFileName: 'orb'},
    sourcemap: false,
    minify: true,
    rolldownOptions: {output: {codeSplitting: false}}
  }
});
