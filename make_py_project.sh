#!/bin/bash
echo "--- Python Project Creator (Poetry + src Layout) ---"
echo "----------------------------------------------------"


#1. ask for project mode
echo "What would you like to do?"
echo "1) Create a brand new project and directory."
echo "2) Create a project with src layout in an existing directory."
read -p "Select an option (1 or 2): " MODE

if [ "$MODE" == "1" ];  then
	read -p "Enter the full path or name for the new directory: " NEW_DIR
	mkdir -p "$NEW_DIR"
	cd "$NEW_DIR" || exit
	echo "Moved to directory: $(pwd)"
elif [ "$MODE" == "2" ]; then
	echo "Proceeding in current directory: $(pwd)"
else
	echo "Invalid option. Exiting."
	exit 1
fi

#2. Get name of current directory
PROJECT_ROOT_NAME=$(basename "$(pwd)")
#Convert  name to snakecase for python package name
#this replaces dashes with underscores and converts to lowercase.
PROJECT_PACKAGE_NAME=$(echo "$PROJECT_ROOT_NAME" | tr '-' '_' | tr '[:upper:]' '[:lower:]')

#3. ask for pyenv version
read -p "Would you like to set a local python version using pyenv? (y/n): " SET_PY
if [[ "$SET_PY" == "y" || "$SET_PY" == "yes" ]]; then
	read -p "Enter pyenv installed python version: " PY_VER
	if pyenv versions | grep -q -w "$PY_VER"; then
		pyenv local "$PY_VER"
		echo "Local pyenv version set to: "
		pyenv version
	else
		echo "Version not installed, run 'pyenv install $PY_VER to install. Exiting"
		exit 1
	fi
fi



read -p "Is Poetry installed and configured? (y/n): " POETRY_READY
POETRY_READY=$(echo "$POETRY_READY" | tr '[:upper:]' '[:lower:]')
if [[ "$POETRY_READY" == "y" || "$POETRY_READY" == "yes" || -z "$POETRY_READY" ]]; then
	mkdir -p src/"$PROJECT_PACKAGE_NAME" tests
	touch src/"$PROJECT_PACKAGE_NAME"/__init__.py

	if [ ! -f "src/$PROJECT_PACKAGE_NAME/main.py" ]; then
		cat <<EOF > src/"$PROJECT_PACKAGE_NAME"/main.py
def start():
	print("Project '$PROJECT_PACKAGE_NAME' is now live!")

if __name__ == "__main__":
	start()
EOF
	fi
	touch README.md .env.example
	echo "------------------------------------"
	echo "File structure created successfully!"
	if [ -f "pyproject.toml" ]; then
		echo "A pyproject.toml already exists. Skipping 'poetry init'."
	else
		poetry init
		poetry config virtualenvs.in-project true --local
	fi

	if ! grep -q "from = \"src\"" pyproject.toml; then
	cat <<EOF >> pyproject.toml
[tool.poetry.scripts]
start = "$PROJECT_PACKAGE_NAME.main:start"

[[tool.poetry.packages]]
include = "$PROJECT_PACKAGE_NAME"
from = "src"
EOF
	fi
	poetry install
else	
	read -p "Create src directory structure without Poetry? (y/n): " CONTINUE_NO_POETRY
	if [[ "$CONTINUE_NO_POETRY" == "y" || "$CONTINUE_NO_POETRY" == "yes" || -z "$CONTINUE_NO_POETRY" ]]; then
		echo "Creating src directory structure without Poetry..."
		mkdir -p src/"$PROJECT_PACKAGE_NAME" tests
		touch src/"$PROJECT_PACKAGE_NAME"/__init__.py

		if [ ! -f "src/$PROJECT_PACKAGE_NAME/main.py" ]; then
			cat <<EOF > src/"$PROJECT_PACKAGE_NAME"/main.py
def start():
	print("Project '$PROJECT_PACKAGE_NAME' is now live!")

if __name__ == "__main__":
	start()
EOF
		fi		
		touch README.md .env.example
		echo "------------------------------------"
		echo "File structure created successfully!"
	else
		echo "Exiting. Please install and configure Poetry before running this script."
		exit 1
	fi

fi


#5.b Create .gitignore
if [ ! -s ".gitignore" ]; then
    cat <<EOF > .gitignore
# Byte-compiled / build files
__pycache__/
*.py[cod]
*$py.class

# Virtual environments
.venv/
venv/
env/
.env

# Packaging
build/
dist/
*.egg-info/

# Testing / caches
.pytest_cache/
.coverage
htmlcov/

# Type check / cache
.mypy_cache/

# IDEs and editor temp files
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store

# Logs and temp
logs/
*.log
tmp/

# custom
*.gpg
*.db
notebooks/.ipynb_checkpoints/
EOF
    echo ">>> Populated .gitignore with Python defaults."
fi


touch tests/__init__.py

if [ ! -f tests/test_main.py ]; then
	cat <<EOF > tests/test_main.py
from $PROJECT_PACKAGE_NAME import main

def test_start_output():
	assert True
EOF
	echo "Created initial test template"
fi

echo "------------------------------------"
echo "File structure created successfully!"
if [[ "$POETRY_READY" == "y" || "$POETRY_READY" == "yes" || -z "$POETRY_READY" ]]; then
    echo "Run 'poetry run start' to test."
else
    echo "You can now manually configure your environment."
fi
