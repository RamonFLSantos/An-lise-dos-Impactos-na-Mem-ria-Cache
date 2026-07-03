#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>

/* ===== ESTRUTURAS ===== */

typedef struct {
    int  valido;   /* 1 se a linha contém dados válidos */
    long rotulo;   /* tag/rótulo do bloco de memória    */
    int  dirty;    /* 1 se modificada (write-back)       */
    int  lru;      /* contador LRU (maior = mais antigo) */
} LinhaCache;

typedef struct {
    /* Parâmetros */
    int   politica_escrita;   /* 0=write-through, 1=write-back */
    int   tam_bloco;          /* bytes por linha                */
    int   num_blocos;         /* total de linhas na cache       */
    int   associatividade;    /* linhas por conjunto            */
    int   hit_time;           /* ns para acerto                 */
    char  politica_subst[8]; /* "LRU" ou "RANDOM"              */
    int   mem_time;           /* ns para acesso à MP            */

    /* Derivados */
    int   num_conjuntos;      /* num_blocos / associatividade   */
    int   bits_offset;        /* log2(tam_bloco)                */
    int   bits_indice;        /* log2(num_conjuntos)            */

    /* Linhas */
    LinhaCache *linhas;       /* vetor [num_blocos]             */

    /* Contadores */
    long total_r;             /* leituras no arquivo            */
    long total_w;             /* escritas no arquivo            */
    long hit_r;               /* acertos de leitura             */
    long hit_w;               /* acertos de escrita             */
    long mp_leituras;         /* leituras na memória principal  */
    long mp_escritas;         /* escritas na memória principal  */
} Cache;

/* ===== FUNÇÕES AUXILIARES ===== */

static int log2_int(int v) {
    int r = 0;
    while (v > 1) { v >>= 1; r++; }
    return r;
}

/* Retorna índice da linha dentro do conjunto para o rótulo dado (-1 se miss) */
static int busca_conjunto(Cache *c, int conjunto, long rotulo) {
    int base = conjunto * c->associatividade;
    for (int i = 0; i < c->associatividade; i++) {
        LinhaCache *l = &c->linhas[base + i];
        if (l->valido && l->rotulo == rotulo)
            return base + i;
    }
    return -1;
}

/* Atualiza contadores LRU após acesso à linha 'idx' dentro do conjunto */
static void atualiza_lru(Cache *c, int conjunto, int idx_acesso) {
    int base = conjunto * c->associatividade;
    int ordem_antiga = c->linhas[idx_acesso].lru;
    for (int i = 0; i < c->associatividade; i++) {
        LinhaCache *l = &c->linhas[base + i];
        if (l->valido && c->linhas[base + i].lru < ordem_antiga)
            l->lru++;
    }
    c->linhas[idx_acesso].lru = 0; /* recém usado = 0 (menor = mais novo) */
}

/* Escolhe vítima no conjunto: LRU ou aleatória. Retorna índice global. */
static int escolhe_vitima(Cache *c, int conjunto) {
    int base = conjunto * c->associatividade;

    /* Primeiro procura linha inválida (posição livre) */
    for (int i = 0; i < c->associatividade; i++) {
        if (!c->linhas[base + i].valido)
            return base + i;
    }

    if (strcmp(c->politica_subst, "LRU") == 0) {
        int vitima = base;
        for (int i = 1; i < c->associatividade; i++) {
            if (c->linhas[base + i].lru > c->linhas[vitima].lru)
                vitima = base + i;
        }
        return vitima;
    } else { /* RANDOM */
        return base + (rand() % c->associatividade);
    }
}

/* Extrai campos do endereço */
static void decompoe_endereco(Cache *c, unsigned int addr,
                               long *rotulo, int *conjunto) {
    int indice_mask = c->num_conjuntos - 1;
    /* offset = addr & offset_mask  (não usado além do mapeamento) */
    *conjunto = (addr >> c->bits_offset) & indice_mask;
    *rotulo   = (long)(addr >> (c->bits_offset + c->bits_indice));
}

/* ===== OPERAÇÕES DE LEITURA / ESCRITA ===== */

static void acessa_leitura(Cache *c, unsigned int addr) {
    long rotulo; int conjunto;
    decompoe_endereco(c, addr, &rotulo, &conjunto);

    int idx = busca_conjunto(c, conjunto, rotulo);
    if (idx >= 0) {
        /* HIT */
        c->hit_r++;
        if (strcmp(c->politica_subst, "LRU") == 0)
            atualiza_lru(c, conjunto, idx);
    } else {
        /* MISS – carrega bloco da MP */
        c->mp_leituras++;
        int vitima = escolhe_vitima(c, conjunto);
        LinhaCache *l = &c->linhas[vitima];

        /* Se write-back e dirty, grava de volta na MP */
        if (c->politica_escrita == 1 && l->valido && l->dirty) {
            c->mp_escritas++;
            l->dirty = 0;
        }

        l->valido = 1;
        l->rotulo = rotulo;
        l->dirty  = 0;

        if (strcmp(c->politica_subst, "LRU") == 0)
            atualiza_lru(c, conjunto, vitima);
    }
}

static void acessa_escrita(Cache *c, unsigned int addr) {
    long rotulo; int conjunto;
    decompoe_endereco(c, addr, &rotulo, &conjunto);

    int idx = busca_conjunto(c, conjunto, rotulo);

    if (c->politica_escrita == 0) {
        /* ===== WRITE-THROUGH ===== */
        c->mp_escritas++; /* sempre escreve na MP */
        if (idx >= 0) {
            /* HIT: atualiza cache e MP (já contabilizado) */
            c->hit_w++;
            if (strcmp(c->politica_subst, "LRU") == 0)
                atualiza_lru(c, conjunto, idx);
        }
        /* MISS (write-non-allocate): não aloca na cache */
    } else {
        /* ===== WRITE-BACK ===== */
        if (idx >= 0) {
            /* HIT: marca dirty */
            c->hit_w++;
            c->linhas[idx].dirty = 1;
            if (strcmp(c->politica_subst, "LRU") == 0)
                atualiza_lru(c, conjunto, idx);
        } else {
            /* MISS (write-allocate): carrega bloco e marca dirty */
            c->mp_leituras++;
            int vitima = escolhe_vitima(c, conjunto);
            LinhaCache *l = &c->linhas[vitima];

            if (l->valido && l->dirty)
                c->mp_escritas++;

            l->valido = 1;
            l->rotulo = rotulo;
            l->dirty  = 1;

            if (strcmp(c->politica_subst, "LRU") == 0)
                atualiza_lru(c, conjunto, vitima);
        }
    }
}

/* Flush final: grava linhas dirty de volta na MP (write-back) */
static void flush_cache(Cache *c) {
    if (c->politica_escrita != 1) return;
    for (int i = 0; i < c->num_blocos; i++) {
        if (c->linhas[i].valido && c->linhas[i].dirty) {
            c->mp_escritas++;
            c->linhas[i].dirty = 0;
        }
    }
}

/* ===== IMPRESSÃO DE RESULTADOS ===== */

static void imprime_resultados(Cache *c, const char *arquivo) {
    long total    = c->total_r + c->total_w;
    long hit_total = c->hit_r + c->hit_w;

    double hr_r  = (c->total_r > 0) ? (double)c->hit_r  / c->total_r  * 100.0 : 0.0;
    double hr_w  = (c->total_w > 0) ? (double)c->hit_w  / c->total_w  * 100.0 : 0.0;
    double hr_g  = (total      > 0) ? (double)hit_total / total        * 100.0 : 0.0;

    /* Tempo médio: hit_time + (1-hr)*mem_time */
    double miss_rate = 1.0 - hr_g / 100.0;
    double amat = c->hit_time + miss_rate * c->mem_time;

    printf("============================================================\n");
    printf("  SIMULADOR DE CACHE – RESULTADOS\n");
    printf("============================================================\n\n");

    printf("--- Parâmetros de Entrada ---\n");
    printf("Arquivo de endereços  : %s\n", arquivo);
    printf("Política de escrita   : %s\n", c->politica_escrita == 0 ? "write-through (0)" : "write-back (1)");
    printf("Tamanho do bloco      : %d bytes\n", c->tam_bloco);
    printf("Número de blocos      : %d\n", c->num_blocos);
    printf("Associatividade       : %d vias\n", c->associatividade);
    printf("Número de conjuntos   : %d\n", c->num_conjuntos);
    printf("Hit time              : %d ns\n", c->hit_time);
    printf("Política de subs.     : %s\n", c->politica_subst);
    printf("Tempo acesso MP       : %d ns\n", c->mem_time);
    printf("\n");

    printf("--- Endereços no Arquivo ---\n");
    printf("Total de endereços    : %ld\n", total);
    printf("  Leituras (R)        : %ld\n", c->total_r);
    printf("  Escritas (W)        : %ld\n", c->total_w);
    printf("\n");

    printf("--- Acesso à Memória Principal ---\n");
    printf("Leituras na MP        : %ld\n", c->mp_leituras);
    printf("Escritas na MP        : %ld\n", c->mp_escritas);
    printf("\n");

    printf("--- Taxa de Acerto (Hit Rate) ---\n");
    printf("Hit rate leitura      : %.4f%% (%ld/%ld)\n", hr_r, c->hit_r,  c->total_r);
    printf("Hit rate escrita      : %.4f%% (%ld/%ld)\n", hr_w, c->hit_w,  c->total_w);
    printf("Hit rate global       : %.4f%% (%ld/%ld)\n", hr_g, hit_total, total);
    printf("\n");

    printf("--- Tempo Médio de Acesso ---\n");
    printf("AMAT                  : %.4f ns\n", amat);
    printf("============================================================\n");
}

/* ===== MAIN ===== */

int main(int argc, char *argv[]) {
    if (argc < 9) {
        fprintf(stderr,
            "Uso: %s <politica_escrita> <tam_bloco> <num_blocos> <assoc> "
            "<hit_time> <politica_subst> <mem_time> <arquivo>\n"
            "  politica_escrita : 0=write-through, 1=write-back\n"
            "  politica_subst   : LRU ou RANDOM\n"
            "Exemplo: %s 0 64 4096 2 4 LRU 60 addresses.txt\n",
            argv[0], argv[0]);
        return 1;
    }

    srand((unsigned)time(NULL));

    Cache c;
    memset(&c, 0, sizeof(c));

    c.politica_escrita = atoi(argv[1]);
    c.tam_bloco        = atoi(argv[2]);
    c.num_blocos       = atoi(argv[3]);
    c.associatividade  = atoi(argv[4]);
    c.hit_time         = atoi(argv[5]);
    strncpy(c.politica_subst, argv[6], 7);
    c.politica_subst[7] = '\0';
    c.mem_time         = atoi(argv[7]);
    const char *arquivo = argv[8];

    /* Validações básicas */
    if (c.num_blocos % c.associatividade != 0) {
        fprintf(stderr, "Erro: num_blocos deve ser múltiplo da associatividade.\n");
        return 1;
    }

    c.num_conjuntos = c.num_blocos / c.associatividade;
    c.bits_offset   = log2_int(c.tam_bloco);
    c.bits_indice   = log2_int(c.num_conjuntos);

    /* Aloca linhas da cache */
    c.linhas = (LinhaCache *)calloc(c.num_blocos, sizeof(LinhaCache));
    if (!c.linhas) {
        fprintf(stderr, "Erro: falha na alocação de memória.\n");
        return 1;
    }

    /* Inicializa LRU com valores distintos para evitar empate */
    for (int s = 0; s < c.num_conjuntos; s++) {
        int base = s * c.associatividade;
        for (int i = 0; i < c.associatividade; i++)
            c.linhas[base + i].lru = i; /* 0=mais novo, assoc-1=mais velho */
    }

    /* Abre arquivo de endereços */
    FILE *fp = fopen(arquivo, "r");
    if (!fp) {
        fprintf(stderr, "Erro: não foi possível abrir '%s'.\n", arquivo);
        free(c.linhas);
        return 1;
    }

    char linha[32];
    while (fgets(linha, sizeof(linha), fp)) {
        unsigned int addr;
        char op;
        if (sscanf(linha, "%x %c", &addr, &op) != 2) continue;

        if (op == 'R' || op == 'r') {
            c.total_r++;
            acessa_leitura(&c, addr);
        } else if (op == 'W' || op == 'w') {
            c.total_w++;
            acessa_escrita(&c, addr);
        }
    }
    fclose(fp);

    /* Flush final (write-back: grava linhas dirty) */
    flush_cache(&c);

    imprime_resultados(&c, arquivo);

    free(c.linhas);
    return 0;
}
