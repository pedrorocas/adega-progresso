# 🍷 Adega Progresso — Sistema de Estoque de Vinhos

Aplicação web desenvolvida em **Python + Flask** para controle de estoque, cadastro de vinhos e registro de vendas.  
Projeto criado para a **ExpoTech UniFecaf** como demonstração de sistema CRUD com interface moderna.

---

## 🚀 Funcionalidades
- Login e cadastro de usuários com senha criptografada  
- Dashboard com indicadores de estoque e vendas  
- Cadastro, edição e exclusão de vinhos  
- Registro de vendas e baixa automática do estoque  
- Filtro por data e totalização das vendas  
- Tema visual em tons de vinho, champanhe e dourado 🍇  

---

## 🛠️ Tecnologias
- Python 3  
- Flask  
- SQLite  
- TailwindCSS  
- HTML / CSS  

---

## 💻 Como executar localmente

```bash
# clonar o repositório
git clone https://github.com/pedrorocas/adega-progresso.git
cd Projeto_Flask

# criar ambiente virtual
python -m venv venv
venv\Scripts\activate   # (Windows)

# instalar dependências
pip install flask flask-bcrypt

# executar o app
python app.py
