import subprocess
import re
import os
import sys
import csv
import matplotlib.pyplot as plt

SIMULADOR = "./simula_cache.exe" if os.name == "nt" else "./simula_cache"
ARQUIVO = "../entradas/oficial.cache"
RESULTADOS = "../resultados"

os.makedirs(RESULTADOS, exist_ok=True)

def salvar_csv(nome, cabecalho, linhas):
    with open(os.path.join(RESULTADOS, nome), "w", newline="", encoding="utf-8") as arq:
        writer = csv.writer(arq)
        writer.writerow(cabecalho)
        writer.writerows(linhas)

def grafico_linha(nome, titulo, eixo_x, eixo_y, xlabel, ylabel):
    plt.figure(figsize=(8,5))
    plt.plot(eixo_x, eixo_y, marker="o")
    plt.title(titulo)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(os.path.join(RESULTADOS, nome))
    plt.close()

def grafico_duplo(nome, titulo, eixo_x, y1, y2, xlabel, ylabel, legenda1, legenda2):
    plt.figure(figsize=(8,5))
    plt.plot(eixo_x, y1, marker="o", label=legenda1)
    plt.plot(eixo_x, y2, marker="o", label=legenda2)
    plt.title(titulo)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(RESULTADOS, nome))
    plt.close()

def rodar(politica_esc, tam_bloco, num_blocos, assoc, hit_time, politica_sub, mem_time, arquivo=ARQUIVO):
    cmd = [
        SIMULADOR,
        str(politica_esc),
        str(tam_bloco),
        str(num_blocos),
        str(assoc),
        str(hit_time),
        politica_sub,
        str(mem_time),
        arquivo
    ]

    try:
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            text=True
        )
    except subprocess.CalledProcessError:
        print("Erro ao executar:", " ".join(cmd))
        return None

    def extrai(pattern, texto, grupo=1, tipo=float):
        m = re.search(pattern, texto)
        if m:
            return tipo(m.group(grupo))
        return None

    return {
        "hit_rate_global": extrai(r"Hit rate global\s+:\s+([\d.]+)%", out),
        "hit_rate_leitura": extrai(r"Hit rate leitura\s+:\s+([\d.]+)%", out),
        "hit_rate_escrita": extrai(r"Hit rate escrita\s+:\s+([\d.]+)%", out),
        "amat": extrai(r"AMAT\s+:\s+([\d.]+)", out),
        "mp_leituras": extrai(r"Leituras na MP\s+:\s+(\d+)", out, tipo=int),
        "mp_escritas": extrai(r"Escritas na MP\s+:\s+(\d+)", out, tipo=int)
    }

def tam_cache_kb(num_blocos, tam_bloco):
    return num_blocos * tam_bloco / 1024

def exp1_tamanho_cache(arquivo=ARQUIVO):
    print("\n" + "="*60)
    print("EXPERIMENTO 1 – Impacto do Tamanho da Cache")
    print("="*60)
    print(f"{'Num Blocos':>12} {'Tam Cache (KB)':>16} {'Hit Rate (%)':>14} {'AMAT (ns)':>12} {'Leit MP':>10} {'Esc MP':>8}")
    print("-"*75)

    rows = []
    nb = 8
    prev_hr = -1
    estavel = 0

    while True:
        r = rodar(0, 128, nb, 4, 4, "LRU", 60, arquivo)

        if r is None:
            break

        hr = r["hit_rate_global"]
        tc = tam_cache_kb(nb, 128)

        print(f"{nb:>12} {tc:>16.1f} {hr:>14.4f} {r['amat']:>12.4f} {r['mp_leituras']:>10} {r['mp_escritas']:>8}")

        rows.append([
            nb,
            tc,
            hr,
            r["amat"],
            r["mp_leituras"],
            r["mp_escritas"]
        ])

        if prev_hr >= 0 and abs(hr - prev_hr) < 0.01:
            estavel += 1
            if estavel >= 2:
                break
        else:
            estavel = 0

        prev_hr = hr
        nb *= 2

    salvar_csv(
        "exp1.csv",
        [
            "Num Blocos",
            "Tam Cache (KB)",
            "Hit Rate",
            "AMAT",
            "Leit MP",
            "Esc MP"
        ],
        rows
    )

    grafico_linha(
        "exp1.png",
        "Impacto do Tamanho da Cache",
        [r[1] for r in rows],
        [r[2] for r in rows],
        "Tamanho da Cache (KB)",
        "Hit Rate (%)"
    )

    return rows


def exp2_tamanho_bloco(arquivo=ARQUIVO):
    print("\n" + "="*60)
    print("EXPERIMENTO 2 – Impacto do Tamanho do Bloco")
    print("="*60)
    print(f"{'Tam Bloco (B)':>15} {'Num Blocos':>12} {'Hit Rate (%)':>14} {'AMAT (ns)':>12} {'Leit MP':>10} {'Esc MP':>8}")
    print("-"*75)

    cache_bytes = 8 * 1024
    rows = []

    tb = 8

    while tb <= 4096:

        nb = cache_bytes // tb

        if nb < 2:
            break

        r = rodar(0, tb, nb, 2, 4, "LRU", 60, arquivo)

        if r is None:
            break

        print(f"{tb:>15} {nb:>12} {r['hit_rate_global']:>14.4f} {r['amat']:>12.4f} {r['mp_leituras']:>10} {r['mp_escritas']:>8}")

        rows.append([
            tb,
            nb,
            r["hit_rate_global"],
            r["amat"],
            r["mp_leituras"],
            r["mp_escritas"]
        ])

        tb *= 2

    salvar_csv(
        "exp2.csv",
        [
            "Tam Bloco",
            "Num Blocos",
            "Hit Rate",
            "AMAT",
            "Leit MP",
            "Esc MP"
        ],
        rows
    )

    grafico_linha(
        "exp2.png",
        "Impacto do Tamanho do Bloco",
        [r[0] for r in rows],
        [r[2] for r in rows],
        "Tamanho do Bloco (Bytes)",
        "Hit Rate (%)"
    )

    return rows

def exp3_associatividade(arquivo=ARQUIVO):
    print("\n" + "="*60)
    print("EXPERIMENTO 3 – Impacto da Associatividade")
    print("="*60)
    print(f"{'Assoc':>8} {'Num Blocos':>12} {'Hit Rate (%)':>14} {'AMAT (ns)':>12} {'Leit MP':>10} {'Esc MP':>8}")
    print("-"*65)

    nb_total = 64
    rows = []

    assoc = 1

    while assoc <= nb_total:

        r = rodar(1, 128, nb_total, assoc, 4, "LRU", 60, arquivo)

        if r is None:
            break

        print(f"{assoc:>8} {nb_total:>12} {r['hit_rate_global']:>14.4f} {r['amat']:>12.4f} {r['mp_leituras']:>10} {r['mp_escritas']:>8}")

        rows.append([
            assoc,
            nb_total,
            r["hit_rate_global"],
            r["amat"],
            r["mp_leituras"],
            r["mp_escritas"]
        ])

        assoc *= 2

    salvar_csv(
        "exp3.csv",
        [
            "Associatividade",
            "Num Blocos",
            "Hit Rate",
            "AMAT",
            "Leit MP",
            "Esc MP"
        ],
        rows
    )

    grafico_linha(
        "exp3.png",
        "Impacto da Associatividade",
        [r[0] for r in rows],
        [r[2] for r in rows],
        "Associatividade",
        "Hit Rate (%)"
    )

    return rows


def exp4_politica_subst(arquivo=ARQUIVO):
    print("\n" + "="*60)
    print("EXPERIMENTO 4 – Impacto da Política de Substituição")
    print("="*60)
    print(f"{'Num Blocos':>12} {'Tam Cache (KB)':>16} {'HR LRU (%)':>12} {'HR RAND (%)':>13} {'AMAT LRU':>10} {'AMAT RAND':>11}")
    print("-"*78)

    rows = []

    nb = 16
    prev_lru = -1
    prev_rand = -1
    estavel = 0

    while True:

        r_lru = rodar(0, 128, nb, 4, 4, "LRU", 60, arquivo)
        r_rand = rodar(0, 128, nb, 4, 4, "RANDOM", 60, arquivo)

        if r_lru is None or r_rand is None:
            break

        tc = tam_cache_kb(nb, 128)

        print(f"{nb:>12} {tc:>16.1f} {r_lru['hit_rate_global']:>12.4f} {r_rand['hit_rate_global']:>13.4f} {r_lru['amat']:>10.4f} {r_rand['amat']:>11.4f}")

        rows.append([
            nb,
            tc,
            r_lru["hit_rate_global"],
            r_rand["hit_rate_global"],
            r_lru["amat"],
            r_rand["amat"],
            r_lru["mp_leituras"],
            r_lru["mp_escritas"],
            r_rand["mp_leituras"],
            r_rand["mp_escritas"]
        ])

        if prev_lru >= 0 and abs(r_lru["hit_rate_global"] - prev_lru) < 0.01 and abs(r_rand["hit_rate_global"] - prev_rand) < 0.01:
            estavel += 1
            if estavel >= 2:
                break
        else:
            estavel = 0

        prev_lru = r_lru["hit_rate_global"]
        prev_rand = r_rand["hit_rate_global"]

        nb *= 2

    salvar_csv(
        "exp4.csv",
        [
            "Num Blocos",
            "Tam Cache (KB)",
            "HR LRU",
            "HR RANDOM",
            "AMAT LRU",
            "AMAT RANDOM",
            "Leit LRU",
            "Esc LRU",
            "Leit RANDOM",
            "Esc RANDOM"
        ],
        rows
    )

    grafico_duplo(
        "exp4.png",
        "Política de Substituição",
        [r[1] for r in rows],
        [r[2] for r in rows],
        [r[3] for r in rows],
        "Cache (KB)",
        "Hit Rate (%)",
        "LRU",
        "RANDOM"
    )

    return rows


def exp5_largura_banda(arquivo=ARQUIVO):

    print("\n" + "="*60)
    print("EXPERIMENTO 5 – Largura de Banda da Memória")
    print("="*60)

    configs = [
        (8,64,2),
        (8,64,4),
        (8,128,2),
        (8,128,4),
        (16,64,2),
        (16,64,4),
        (16,128,2),
        (16,128,4),
    ]

    for politica, nome in [(0,"WRITE-THROUGH"),(1,"WRITE-BACK")]:

        print(f"\n--- {nome} ---")
        print(f"{'Cache(KB)':>10} {'Bloco(B)':>10} {'Assoc':>7} {'Leit MP':>10} {'Esc MP':>10} {'Total':>10}")
        print("-"*60)

        rows=[]

        total_leit=0
        total_esc=0
        n=0

        for tc,tb,assoc in configs:

            nb=(tc*1024)//tb

            r=rodar(politica,tb,nb,assoc,4,"LRU",60,arquivo)

            if r is None:
                continue

            lm=r["mp_leituras"]
            em=r["mp_escritas"]
            tot=lm+em

            print(f"{tc:>10} {tb:>10} {assoc:>7} {lm:>10} {em:>10} {tot:>10}")

            rows.append([tc,tb,assoc,lm,em,tot])

            total_leit+=lm
            total_esc+=em
            n+=1

        rows.append([
            "Média",
            "",
            "",
            round(total_leit/n,4),
            round(total_esc/n,4),
            round((total_leit+total_esc)/n,4)
        ])

        salvar_csv(
            f"exp5_{nome.lower()}.csv",
            [
                "Cache(KB)",
                "Bloco(B)",
                "Assoc",
                "Leit MP",
                "Esc MP",
                "Total"
            ],
            rows
        )

        print(f"{'Média':>28} {total_leit/n:>10.4f} {total_esc/n:>10.4f} {(total_leit+total_esc)/n:>10.4f}")

if __name__ == "__main__":

    if len(sys.argv) > 1:
        ARQUIVO = sys.argv[1]

    if not os.path.isfile(ARQUIVO):
        print(f"AVISO: arquivo '{ARQUIVO}' não encontrado.")
        sys.exit(1)

    if not os.path.isfile(SIMULADOR):
        print(f"ERRO: simulador '{SIMULADOR}' não encontrado.")
        sys.exit(1)

    print("\nGerando resultados...\n")

    exp1_tamanho_cache(ARQUIVO)
    exp2_tamanho_bloco(ARQUIVO)
    exp3_associatividade(ARQUIVO)
    exp4_politica_subst(ARQUIVO)
    exp5_largura_banda(ARQUIVO)

    print("\n" + "=" * 60)
    print("EXPERIMENTOS CONCLUÍDOS")
    print("=" * 60)
    print(f"Arquivos CSV salvos em: {os.path.abspath(RESULTADOS)}")
    print(f"Gráficos PNG salvos em: {os.path.abspath(RESULTADOS)}")