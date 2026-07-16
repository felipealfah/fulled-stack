-- Migration 022: Corrige estado pós-021
-- Problema 1: id_int_legado perdeu DEFAULT nextval() no RENAME de id → id_int_legado
-- Problema 2: id_uuid foi re-adicionada pelo re-run idempotente de 019 após 021 já ter renomeado para id
-- Ambas as correções são idempotentes

-- 1. Restaurar DEFAULT da sequência serial em id_int_legado
DO $$
BEGIN
    -- Só aplicar se o DEFAULT ainda não estiver definido
    IF (
        SELECT column_default IS NULL
        FROM information_schema.columns
        WHERE table_name = 'projetos' AND column_name = 'id_int_legado'
    ) THEN
        ALTER TABLE projetos
            ALTER COLUMN id_int_legado
            SET DEFAULT nextval('projetos_id_seq'::regclass);
        RAISE NOTICE 'DEFAULT nextval restaurado em id_int_legado';
    ELSE
        RAISE NOTICE 'id_int_legado já tem DEFAULT — nenhuma ação necessária';
    END IF;
END $$;

-- 2. Remover coluna duplicada id_uuid (re-adicionada pelo re-run de 019)
--    id já é o UUID canônico (renomeado de id_uuid em 021)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'projetos' AND column_name = 'id_uuid'
    ) THEN
        ALTER TABLE projetos DROP COLUMN id_uuid;
        RAISE NOTICE 'Coluna id_uuid duplicada removida';
    ELSE
        RAISE NOTICE 'id_uuid não existe — nenhuma ação necessária';
    END IF;
END $$;
