# Внешние инструменты

Сюда клонируются и здесь собираются программы, которые мост запускает сам. В git они не
попадают (см. `.gitignore`).

```
tools/
    llama.cpp/               llama-server — текстовая модель     scripts/setup-llama.sh
    stable-diffusion.cpp/    sd-server — картинки                scripts/setup-images.sh
```

Оба скрипта можно запускать повторно: они обновляют исходники и пересобирают.
