"""DHI MIKE21 mesh functions
"""

# Author: Robert Wall

import numpy as np
from dotenv import load_dotenv, find_dotenv
import os
import clr

# Set path to MIKE SDK
load_dotenv(find_dotenv())
sdk_path = os.getenv('MIKE_SDK')
dfs_dll = os.getenv('MIKE_DFS')
clr.AddReference(os.path.join(sdk_path, dfs_dll))
clr.AddReference('System')

# Import .NET libraries
import DHI.Generic.MikeZero.DFS as dfs
import System

import _utils


class Mesh():

    def __init__(self, filename=None):
        self.filename = filename
        self._file_input = False
        self.zUnitKey = 1000  # Default value (1000 = meter)

        if filename is not None:
            self.read_mesh()

    def read_mesh(self, filename=None):
        '''
        Read in .mesh file
        '''
        if filename is None:
            filename = self.filename

        dfs_obj = dfs.mesh.MeshFile.ReadMesh(filename)
        mesh_in = _read_mesh(dfs_obj)

        self.nodes = mesh_in[0]
        self.node_ids = mesh_in[1]
        self.node_boundary_codes = mesh_in[2]
        self.element_table = mesh_in[3]
        self.node_table = mesh_in[4]
        self.elements = mesh_in[5]
        self.element_ids = mesh_in[6]
        self.projection = str(dfs_obj.ProjectionString)
        self.zUnitKey = dfs_obj.EumQuantity.Unit
        self._file_input = True
        self.num_elements = len(self.elements)
        self.num_nodes = len(self.nodes)

    def summary(self):
        '''
        Summarise .mesh file
        '''
        if self._file_input:
            print("Input mesh file: {}".format(self.filename))
        else:
            print("No .mesh input file")

        try:
            print("Num. Elmts = {}".format(self.num_elements))
            print("Num. Nodes = {}".format(self.num_nodes))
            print("Mean elevation = {}".format(np.mean(self.nodes[:, 2])))
            print("Projection = \n {}".format(self.projection))
        except AttributeError:
            print("Object has no element or node properties. Read in mesh.")

    def write_mesh(self, output_name):
        '''
        Write new mesh file
        '''
        _write_mesh(filename=output_name,
                    nodes=self.nodes,
                    node_id=self.node_ids,
                    node_boundary_code=self.node_boundary_codes,
                    element_table=self.element_table,
                    element_ids=self.element_ids,
                    proj=self.projection,
                    zUnitKey=self.zUnitKey)

    def interpolate_rasters(self, raster_list, method='nearest'):
        '''
        Interpolate multiple raster elevations to mesh nodes
        '''
        import _raster_interpolate as _ri

        for r in raster_list:
            interp_z = _ri.interpolate_from_raster(r, self.nodes[:, 1:3], method)

            # Just consider nodes that overlay raster
            updated_z = np.column_stack((self.nodes[:, 0], interp_z))

            # Sort by node_id
            updated_z_sorted = updated_z[updated_z[:, 0].argsort()]

            # Boolean mask for only updated nodes
            updated_bool = ~np.isnan(updated_z_sorted[:, 1])

            # Drop NaN
            only_updated_z = updated_z_sorted[:, 1][~np.isnan(updated_z_sorted[:, 1])]

            # Update mesh obj nodes only where node was interpolated
            self.nodes[:, 3][updated_bool] = only_updated_z


def _read_mesh(dfs_obj):
    """
    Function description...

    Parameters
    ----------
    input_1 : dtype, shape (n_components,)
        input_1 description...
    input_2 : int
        input_2 description...

    Returns
    -------
    weights : array, shape (n_components,)

    """
    num_nodes = dfs_obj.NumberOfNodes
    num_elements = dfs_obj.NumberOfElements

    # Node coordinates
    nodes = _node_coordinates(dfs_obj)

    # Node ids
    node_ids = _utils.dotnet_arr_to_ndarr(dfs_obj.NodeIds)

    # Node boundary codes
    boundary_code = _utils.dotnet_arr_to_ndarr(dfs_obj.Code)

    # Element table
    ele_table = _element_table(dfs_obj)

    # Node table
    node_table = _node_table(num_nodes, num_elements, ele_table)

    # Element coordinates
    elements = _mesh_element_coordinates(ele_table, nodes)

    # Element ids
    element_ids = _utils.dotnet_arr_to_ndarr(dfs_obj.ElementIds)

    return nodes, node_ids, boundary_code, ele_table, node_table, elements, element_ids


def _node_coordinates(dfs_obj):
    xn = _utils.dotnet_arr_to_ndarr(dfs_obj.X)
    yn = _utils.dotnet_arr_to_ndarr(dfs_obj.Y)
    zn = _utils.dotnet_arr_to_ndarr(dfs_obj.Z)

    return np.column_stack([xn,yn,zn])


def _element_table(dfs_obj):
    table_obj = dfs_obj.ElementTable
    ele_table = np.zeros((len(table_obj), 3), dtype=int)
    for i, e in enumerate(table_obj):
        ele_table[i, :] = _utils.dotnet_arr_to_ndarr(e)
    return ele_table


def _node_table(num_nodes, num_elements, ele_table):
    """ Create node_table from ele_table """

    # Set placeholders for constructing node-to-element-table (node_table)
    e = np.arange(num_elements)
    u = np.ones(num_elements)
    I = np.concatenate((e, e, e))
    J = np.concatenate((ele_table[:,0],ele_table[:,1],ele_table[:,2]))
    K = np.concatenate((u*1, u*2, u*3))

    # Construct node_table
    count = np.zeros((num_nodes,1))
    for i in range(len(I)):
        count[J[i-1]-1] = count[J[i-1]-1]+1
    num_cols = int(count.max())

    node_table = np.zeros((num_nodes,num_cols), dtype='int')
    count = np.zeros((num_nodes,1))
    for i in range(len(I)):
        count[J[i-1]-1] = count[J[i-1]-1]+1
        node_table[J[i-1]-1, int(count[J[i-1]-1])-1] = I[i]

    return node_table


def _mesh_element_coordinates(element_tables, nodes):

    # Node coords
    xn = nodes[:, 0]
    yn = nodes[:, 1]
    zn = nodes[:, 2]

    # Elmt node index mapping (minus 1 because python indexing)
    node_map = element_tables[:, 1:].astype('int') - 1

    # Take mean of nodes mapped to element
    xe = np.mean(xn[node_map], axis=1)
    ye = np.mean(yn[node_map], axis=1)
    ze = np.mean(zn[node_map], axis=1)

    elmt_numbers = element_tables[:, 0]

    return np.stack([elmt_numbers, xe, ye, ze], axis=1)


def _write_mesh(filename, nodes, node_id,
                node_boundary_code, element_table,
                element_ids, proj, zUnitKey=1000):
    """
    Function description...

    Parameters
    ----------
    input_1 : dtype, shape (n_components,)
        input_1 description...
    input_2 : int
        input_2 description...

    Returns
    -------
    weights : array, shape (n_components,)

    """

    eum_type = 100079  # Specify item type as 'bathymetry' (MIKE convention)
    num_nodes = len(nodes)

    node_write_fmt = np.column_stack([node_id, nodes, node_boundary_code])
    ele_write_fmt = np.column_stack([element_ids, element_table])

    # Open file to write to
    with open(filename, 'w') as target:
        # Format first line
        first_line = '%i  %i  %i  %s\n' % (eum_type, zUnitKey, num_nodes, proj)
        target.write(first_line)

        # Nodes
        np.savetxt(target, node_write_fmt, fmt='%i %-17.15g %17.15g %17.15g %i',
                   newline='\n', delimiter=' ')

        # Element header
        num_elements = len(ele_write_fmt)

        # Specify only triangular elements
        elmt_header = '%i %i %i\n' % (num_elements, 3, 21)
        target.write(elmt_header)

        # Elements
        np.savetxt(target, ele_write_fmt, fmt='%i', newline='\n', delimiter=' ')
