from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="safe-fix",
    version="1.0.0",
    description="Regression-proof protocol for code fixes. Catches bugs introduced by patches before they ship.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/thinkrevant/Safe_Fix",
    license="Apache-2.0",
    python_requires=">=3.7",
    packages=find_packages(),
    package_data={"safe_fix": ["verifier.py"]},
    entry_points={
        "console_scripts": [
            "safe-fix=safe_fix.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Quality Assurance",
        "Topic :: Software Development :: Testing",
    ],
)
