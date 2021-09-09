import platform
from codecs import open
from os import path

#from Cython.Build import cythonize
from setuptools import Extension, find_packages, setup

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

# This reads the __version__ variable from waveforms/version.py
__version__ = ""
exec(open('waveforms/version.py').read())

requirements = [
    'blinker>=1.4',
    'click>=7.1.2',
    'cryptography>=3.4.7',
    'GitPython>=3.1.14',
    'h5py>=2.7.0',
    'numpy>=1.13.3',
    'ply>=3.11',
    'portalocker>=1.4.0',
    'scikit-learn>=0.24.1',
    'scikit-optimize>=0.8.1',
    'scipy>=1.0.0',
    'SQLAlchemy>=1.4.11',
    'xarray>=0.18.2'
]

setup(
    name="waveforms",
    version=__version__,
    author="feihoo87",
    author_email="feihoo87@gmail.com",
    url="https://github.com/feihoo87/waveforms",
    license = "MIT",
    keywords="signal waveform experiment laboratory",
    description="generate waveforms used in experiment",
    long_description=long_description,
    long_description_content_type='text/markdown',
    packages = find_packages(),
    #ext_modules = cythonize("waveforms/math/prime.pyx"),
    include_package_data = True,
    #data_files=[('waveforms/Data', waveData)],
    entry_points ={'console_scripts': ['wave_server = waveforms.server.__main__:main']},
    install_requires=requirements,
    extras_require={
        'storage': [
            'netcdf4>=1.5.7'
        ],
        'test': [
            'pytest>=4.4.0',
        ],
        'docs': [
            'Sphinx',
            'sphinxcontrib-napoleon',
            'sphinxcontrib-zopeext',
        ],
    },
    python_requires='>=3.9',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: MIT License',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: POSIX :: Linux',
        'Operating System :: MacOS :: MacOS X',
        'Topic :: Scientific/Engineering :: Interface Engine/Protocol Translator',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
    ],
    project_urls={  # Optional
        'Bug Reports': 'https://github.com/feihoo87/waveforms/issues',
        'Source': 'https://github.com/feihoo87/waveforms/',
    },
)
