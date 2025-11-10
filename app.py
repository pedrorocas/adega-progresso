from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_bcrypt import Bcrypt
from functools import wraps
import sqlite3, os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "loja.db"))

import os

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET", "dev-secret")
bcrypt = Bcrypt(app)

# ----------------- DB -----------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                senha_hash TEXT NOT NULL,
                criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS produtos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                uva TEXT,
                safra TEXT,
                regiao TEXT,
                preco REAL NOT NULL DEFAULT 0,
                estoque INTEGER NOT NULL DEFAULT 0,
                descricao TEXT,
                imagem_url TEXT,
                criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vendas(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                produto_id INTEGER NOT NULL,
                quantidade INTEGER NOT NULL,
                preco_unit REAL NOT NULL,
                total REAL NOT NULL,
                criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(produto_id) REFERENCES produtos(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entradas(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                produto_id INTEGER NOT NULL,
                quantidade INTEGER NOT NULL,
                custo_unit REAL,
                observacao TEXT,
                criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(produto_id) REFERENCES produtos(id)
            )
        """)
        conn.commit()


init_db()

# --------------- Helpers --------------
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Faça login para acessar.", "danger")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper

# Filtro para formatar moeda BRL (simples, sem locale)
@app.template_filter("brl")
def brl(value):
    try:
        v = float(value or 0)
        txt = f"{v:,.2f}"
        # 1,234,567.89 -> 1.234.567,89
        return "R$ " + txt.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"

# ---------------- Rotas Auth ----------------
@app.route("/")
def raiz():
    # Se logado, vai para o dashboard; senão, login
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        with get_conn() as conn:
            user = conn.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
        if user and bcrypt.check_password_hash(user["senha_hash"], senha):
            session["user_id"] = user["id"]
            session["user_nome"] = user["nome"]
            flash("Bem-vindo(a) de volta!", "success")
            return redirect(url_for("produtos_list"))
        flash("E-mail ou senha inválidos.", "danger")
    return render_template("login.html")

@app.route("/registrar", methods=["GET", "POST"])
def registrar():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        confirma = request.form.get("confirma", "")
        if not nome or not email or not senha:
            flash("Preencha todos os campos.", "danger")
            return render_template("registrar.html", nome=nome, email=email)
        if senha != confirma:
            flash("As senhas não conferem.", "danger")
            return render_template("registrar.html", nome=nome, email=email)
        senha_hash = bcrypt.generate_password_hash(senha).decode("utf-8")
        try:
            with get_conn() as conn:
                conn.execute("INSERT INTO usuarios (nome, email, senha_hash) VALUES (?, ?, ?)",
                             (nome, email, senha_hash))
                conn.commit()
            flash("Conta criada! Faça login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Já existe uma conta com esse e-mail.", "danger")
    return render_template("registrar.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Você saiu do sistema.", "success")
    return redirect(url_for("login"))

@app.route("/perfil", methods=["GET", "POST"])
@login_required
def perfil():
    with get_conn() as conn:
        user = conn.execute("SELECT id, nome, email FROM usuarios WHERE id = ?", (session["user_id"],)).fetchone()

    if request.method == "POST":
        nova = (request.form.get("nova_senha") or "").strip()
        conf = (request.form.get("confirma") or "").strip()

        if not nova or not conf:
            flash("Preencha os dois campos de senha.", "danger")
            return render_template("perfil.html", user=user)
        if nova != conf:
            flash("As senhas não conferem.", "danger")
            return render_template("perfil.html", user=user)
        if len(nova) < 6:
            flash("A senha deve ter pelo menos 6 caracteres.", "danger")
            return render_template("perfil.html", user=user)

        senha_hash = bcrypt.generate_password_hash(nova).decode("utf-8")
        with get_conn() as conn:
            conn.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (senha_hash, session["user_id"]))
            conn.commit()
        flash("Senha atualizada com sucesso.", "success")
        return redirect(url_for("perfil"))

    return render_template("perfil.html", user=user)


# ---------------- CRUD Vinhos ----------------
@app.route("/produtos")
@login_required
def produtos_list():
    q        = (request.args.get("q") or "").strip()
    uva_f    = (request.args.get("uva") or "").strip()
    regiao_f = (request.args.get("regiao") or "").strip()
    order    = (request.args.get("order") or "recentes").strip()

    # ORDER BY seguro via whitelist
    order_map = {
        "recentes":   "criado_em DESC, id DESC",
        "preco_asc":  "preco ASC, id DESC",
        "preco_desc": "preco DESC, id DESC",
        "nome_asc":   "nome COLLATE NOCASE ASC, id DESC",
    }
    order_by = order_map.get(order, order_map["recentes"])

    # WHERE dinâmico
    where = []
    params = []

    if q:
        where.append("(nome LIKE ? OR uva LIKE ? OR regiao LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    if uva_f:
        where.append("COALESCE(uva,'') = ?")
        params.append(uva_f)
    if regiao_f:
        where.append("COALESCE(regiao,'') = ?")
        params.append(regiao_f)

    sql = "SELECT * FROM produtos"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order_by}"

    with get_conn() as conn:
        produtos = conn.execute(sql, tuple(params)).fetchall()
        # listas para os selects de filtro
        uvas = [r["uva"] for r in conn.execute(
            "SELECT DISTINCT uva FROM produtos WHERE uva IS NOT NULL AND uva <> '' ORDER BY uva COLLATE NOCASE"
        ).fetchall()]
        regioes = [r["regiao"] for r in conn.execute(
            "SELECT DISTINCT regiao FROM produtos WHERE regiao IS NOT NULL AND regiao <> '' ORDER BY regiao COLLATE NOCASE"
        ).fetchall()]

    return render_template(
        "produtos.html",
        produtos=produtos,
        q=q, uva_f=uva_f, regiao_f=regiao_f, order=order,
        uvas=uvas, regioes=regioes
    )


@app.route("/produtos/novo", methods=["GET", "POST"])
@login_required
def produtos_novo():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        uva = request.form.get("uva", "").strip()
        safra = request.form.get("safra", "").strip()
        regiao = request.form.get("regiao", "").strip()
        preco_raw = (request.form.get("preco") or "0").replace(".", "").replace(",", ".")
        estoque = int(request.form.get("estoque") or 0)
        descricao = request.form.get("descricao", "").strip()
        imagem_url = request.form.get("imagem_url", "").strip()
        try:
            preco = float(preco_raw)
        except ValueError:
            preco = 0.0
        if not nome:
            flash("Informe o nome do vinho.", "danger")
            return render_template("produto_form.html", produto=None)
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO produtos (nome, uva, safra, regiao, preco, estoque, descricao, imagem_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (nome, uva, safra, regiao, preco, estoque, descricao, imagem_url))
            conn.commit()
        flash(f'Vinho "{nome}" cadastrado!', "success")
        return redirect(url_for("produtos_list"))
    return render_template("produto_form.html", produto=None)

@app.route("/produtos/<int:pid>/editar", methods=["GET", "POST"])
@login_required
def produtos_editar(pid):
    with get_conn() as conn:
        produto = conn.execute("SELECT * FROM produtos WHERE id = ?", (pid,)).fetchone()
    if not produto:
        flash("Vinho não encontrado.", "danger")
        return redirect(url_for("produtos_list"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        uva = request.form.get("uva", "").strip()
        safra = request.form.get("safra", "").strip()
        regiao = request.form.get("regiao", "").strip()
        preco_raw = (request.form.get("preco") or "0").replace(".", "").replace(",", ".")
        estoque = int(request.form.get("estoque") or 0)
        descricao = request.form.get("descricao", "").strip()
        imagem_url = request.form.get("imagem_url", "").strip()
        try:
            preco = float(preco_raw)
        except ValueError:
            preco = 0.0
        if not nome:
            flash("Informe o nome do vinho.", "danger")
            return render_template("produto_form.html", produto=produto)

        with get_conn() as conn:
            conn.execute("""
                UPDATE produtos
                SET nome=?, uva=?, safra=?, regiao=?, preco=?, estoque=?, descricao=?, imagem_url=?
                WHERE id=?
            """, (nome, uva, safra, regiao, preco, estoque, descricao, imagem_url, pid))
            conn.commit()
        flash(f'Vinho "{nome}" atualizado!', "success")
        return redirect(url_for("produtos_list"))

    return render_template("produto_form.html", produto=produto)

@app.route("/produtos/<int:pid>/deletar", methods=["POST"])
@login_required
def produtos_deletar(pid):
    with get_conn() as conn:
        prod = conn.execute("SELECT nome FROM produtos WHERE id = ?", (pid,)).fetchone()
        if not prod:
            flash("Vinho não encontrado.", "danger")
            return redirect(url_for("produtos_list"))
        conn.execute("DELETE FROM produtos WHERE id = ?", (pid,))
        conn.commit()
    flash(f'Vinho "{prod["nome"]}" removido.', "success")
    return redirect(url_for("produtos_list"))

@app.route("/produtos/<int:pid>")
@login_required
def produto_detalhe(pid):
    with get_conn() as conn:
        p = conn.execute("SELECT * FROM produtos WHERE id = ?", (pid,)).fetchone()
        if not p:
            flash("Vinho não encontrado.", "danger")
            return redirect(url_for("produtos_list"))

        vendas_info = conn.execute("""
            SELECT 
              COALESCE(SUM(quantidade),0) AS qtd_vendida,
              COALESCE(SUM(total),0)      AS valor_vendido
            FROM vendas WHERE produto_id = ?
        """, (pid,)).fetchone()

        entradas_info = conn.execute("""
            SELECT COALESCE(SUM(quantidade),0) AS qtd_entrada
            FROM entradas WHERE produto_id = ?
        """, (pid,)).fetchone()

    return render_template("produto_detalhe.html",
                           p=p,
                           vendas_info=vendas_info,
                           entradas_info=entradas_info)


#Rota de Vendas
from datetime import datetime, date

@app.route("/estoque/entrada", methods=["GET", "POST"])
@login_required
def estoque_entrada():
    if request.method == "POST":
        produto_id = int(request.form.get("produto_id") or 0)
        quantidade = int(request.form.get("quantidade") or 0)
        custo_raw  = (request.form.get("custo_unit") or "").strip()
        observacao = (request.form.get("observacao") or "").strip()

        if produto_id <= 0 or quantidade <= 0:
            flash("Selecione um produto e informe uma quantidade válida.", "danger")
            return redirect(url_for("estoque_entrada"))

        custo_unit = None
        if custo_raw:
            try:
                # aceita 79,90 ou 79.90
                custo_unit = float(custo_raw.replace('.', '').replace(',', '.')) if ',' in custo_raw else float(custo_raw)
            except ValueError:
                custo_unit = None

        with get_conn() as conn:
            prod = conn.execute("SELECT id, nome FROM produtos WHERE id = ?", (produto_id,)).fetchone()
            if not prod:
                flash("Produto não encontrado.", "danger")
                return redirect(url_for("estoque_entrada"))

            conn.execute("""
                INSERT INTO entradas (produto_id, quantidade, custo_unit, observacao)
                VALUES (?,?,?,?)
            """, (produto_id, quantidade, custo_unit, observacao))

            conn.execute("UPDATE produtos SET estoque = estoque + ? WHERE id = ?", (quantidade, produto_id))
            conn.commit()

        flash("Entrada registrada e estoque atualizado!", "success")
        # volta pra ficha do produto para ver o novo estoque
        return redirect(url_for("produto_detalhe", pid=produto_id))

    # GET
    with get_conn() as conn:
        produtos = conn.execute("SELECT id, nome, estoque FROM produtos ORDER BY nome COLLATE NOCASE").fetchall()
    return render_template("estoque_form.html", produtos=produtos)


@app.route("/vendas")
@login_required
def vendas_list():
    d1 = (request.args.get("d1") or "").strip()  # formato YYYY-MM-DD
    d2 = (request.args.get("d2") or "").strip()

    where = []
    params = []

    if d1:
        where.append("date(v.criado_em) >= date(?)")
        params.append(d1)
    if d2:
        where.append("date(v.criado_em) <= date(?)")
        params.append(d2)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    with get_conn() as conn:
        vendas = conn.execute(f"""
            SELECT v.id, v.criado_em, v.quantidade, v.preco_unit, v.total,
                   p.nome AS produto_nome
            FROM vendas v
            JOIN produtos p ON p.id = v.produto_id
            {where_sql}
            ORDER BY v.criado_em DESC, v.id DESC
        """, tuple(params)).fetchall()

        totais = conn.execute(f"""
            SELECT COALESCE(SUM(v.quantidade),0) AS itens,
                   COALESCE(SUM(v.total),0)      AS valor
            FROM vendas v
            {where_sql}
        """, tuple(params)).fetchone()

    return render_template("vendas.html", vendas=vendas, d1=d1, d2=d2, totais=totais)


@app.route("/vendas/nova", methods=["GET", "POST"])
@login_required
def vendas_nova():
    if request.method == "POST":
        produto_id = int(request.form.get("produto_id") or 0)
        quantidade = int(request.form.get("quantidade") or 0)

        if produto_id <= 0 or quantidade <= 0:
            flash("Selecione um produto e informe a quantidade.", "danger")
            return redirect(url_for("vendas_nova"))

        with get_conn() as conn:
            produto = conn.execute("SELECT id, nome, preco, estoque FROM produtos WHERE id = ?", (produto_id,)).fetchone()
            if not produto:
                flash("Produto não encontrado.", "danger")
                return redirect(url_for("vendas_nova"))

            if quantidade > (produto["estoque"] or 0):
                flash(f"Estoque insuficiente de '{produto['nome']}'.", "danger")
                return redirect(url_for("vendas_nova"))

            preco_unit = float(produto["preco"] or 0)
            total = preco_unit * quantidade

            # Transação simples: registra venda e abate estoque
            conn.execute("""
                INSERT INTO vendas (produto_id, quantidade, preco_unit, total)
                VALUES (?, ?, ?, ?)
            """, (produto_id, quantidade, preco_unit, total))
            conn.execute("""
                UPDATE produtos SET estoque = estoque - ? WHERE id = ?
            """, (quantidade, produto_id))
            conn.commit()

        flash("Venda registrada e estoque atualizado!", "success")
        return redirect(url_for("vendas_list"))

    # GET
    with get_conn() as conn:
        produtos = conn.execute("SELECT id, nome, estoque, preco FROM produtos ORDER BY nome COLLATE NOCASE").fetchall()
    return render_template("venda_form.html", produtos=produtos)



# -------------- Dashboard --------------
@app.route("/dashboard")
@login_required
def dashboard():
    # período opcional via querystring ?d1=YYYY-MM-DD&d2=YYYY-MM-DD
    d1 = (request.args.get("d1") or "").strip()
    d2 = (request.args.get("d2") or "").strip()

    with get_conn() as conn:
        kpis = conn.execute("""
            SELECT 
              COUNT(*)                        AS qtd_vinhos,
              COALESCE(SUM(estoque), 0)       AS itens_estoque,
              COALESCE(SUM(preco*estoque),0)  AS valor_estoque
            FROM produtos
        """).fetchone()

        where = []
        params = []
        if d1:
            where.append("date(criado_em) >= date(?)")
            params.append(d1)
        if d2:
            where.append("date(criado_em) <= date(?)")
            params.append(d2)
        where_sql = (" WHERE " + " AND ".join(where)) if where else " WHERE date(criado_em)=date('now','localtime')"  # padrão: hoje

        vendas_range = conn.execute(f"""
            SELECT COALESCE(SUM(quantidade),0) AS itens_vendidos,
                   COALESCE(SUM(total),0)      AS valor_vendido
            FROM vendas
            {where_sql}
        """, tuple(params)).fetchone()

        baixo = conn.execute("""
            SELECT id, nome, estoque
            FROM produtos
            WHERE estoque <= 5
            ORDER BY estoque ASC, nome COLLATE NOCASE
            LIMIT 8
        """).fetchall()

    return render_template(
        "dashboard.html",
        nome=session.get("user_nome"),
        kpis=kpis,
        vendas_hoje=vendas_range,  # mantém o nome usado no template
        baixo=baixo,
        d1=d1,
        d2=d2
    )



if __name__ == "__main__":
    app.run(debug=True)
